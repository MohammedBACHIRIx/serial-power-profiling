import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import serial
import serial.tools.list_ports
import socket
import threading
import time
import re
import collections
import random

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.animation as animation

# --- Mock Serial Simulator for Testing ---
class MockSerial:
    def __init__(self, port, baudrate=9600):
        self.port = port
        self.is_open = True
        self.in_waiting = 0
        self.mode = "WATT"
        self.auto = False
        self._buffer = b""
        self._stop = False
        
        # P2 output is ~85% of P1 for testing efficiency
        self.eff_factor = 0.85 if "P2" in port else 1.0

        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()

    def write(self, data):
        cmd = data.decode('ascii', errors='ignore').strip().upper()
        if cmd == "MA1":
            self.auto = True
        elif cmd == "MA0":
            self.auto = False
        elif cmd in ["WATT", "VAR", "VOLT", "AMP", "PWF"]:
            self.mode = cmd
            
    def read(self, size=1):
        if size > len(self._buffer):
            size = len(self._buffer)
        data = self._buffer[:size]
        self._buffer = self._buffer[size:]
        self.in_waiting = len(self._buffer)
        return data
        
    def _run(self):
        v = 230.0
        i = 2.0 * self.eff_factor
        
        while not self._stop:
            if self.auto:
                v_noise = v + random.uniform(-1.5, 1.5)
                i_noise = i + random.uniform(-0.05, 0.05)
                w_noise = v_noise * i_noise * 0.95 + random.uniform(-2, 2)
                
                if self.mode == "WATT":
                    line = f"U3={v_noise:.1f}E+0 I2={i_noise:.3f}E+0 W={w_noise:.2f}E+0\r"
                elif self.mode == "VAR":
                    var_val = w_noise * 0.2
                    line = f"U3={v_noise:.1f}E+0 I2={i_noise:.3f}E+0 VAR={var_val:.2f}E+0\r"
                elif self.mode == "PWF":
                    line = f"U3={v_noise:.1f}E+0 I2={i_noise:.3f}E+0 PF=0.950E+0\r"
                else:
                    line = f"U3={v_noise:.1f}E+0 I2={i_noise:.3f}E+0 W={w_noise:.2f}E+0\r"
                
                b_line = line.encode('ascii')
                # Inject XON/XOFF noise as documented for ISW8001
                if random.random() > 0.7:
                    b_line = b_line[:5] + b'\x11' + b_line[5:10] + b'\x13' + b_line[10:]
                
                self._buffer += b_line
                self.in_waiting = len(self._buffer)
            
            time.sleep(0.47) # Device sends every ~470ms
            
    def close(self):
        self.is_open = False
        self._stop = True


# --- Universal Connection Handler (Serial COM or TCP/Ethernet for WIZ750SR) ---
class ConnectionHandler:
    def __init__(self, conn_type, target, baudrate=9600):
        self.conn_type = conn_type  # "SERIAL" or "TCP"
        self.target = target        # COM port string OR "IP:PORT"
        self.baudrate = baudrate
        self.serial_conn = None
        self.tcp_sock = None
        self.is_connected = False
        self.thread = None
        self.callback = None

    def connect(self):
        try:
            if self.conn_type == "SERIAL":
                if self.target.startswith("SIMULATOR"):
                    self.serial_conn = MockSerial(self.target, self.baudrate)
                else:
                    self.serial_conn = serial.Serial(self.target, self.baudrate, timeout=1)
            elif self.conn_type == "TCP":
                # Parse host and port
                if ":" in self.target:
                    host, port_str = self.target.split(":", 1)
                    port = int(port_str.strip())
                else:
                    host = self.target.strip()
                    port = 5000  # Default WIZ750SR port
                
                self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.tcp_sock.settimeout(3.0)
                self.tcp_sock.connect((host, port))
                self.tcp_sock.settimeout(0.5)

            self.is_connected = True
            self.send_command("MA1") # Start auto measurement mode
            
            self.thread = threading.Thread(target=self.read_loop, daemon=True)
            self.thread.start()
            return True, "Connected"
        except Exception as e:
            self.disconnect()
            return False, str(e)

    def disconnect(self):
        self.is_connected = False
        try:
            self.send_command("MA0")
            time.sleep(0.05)
        except:
            pass

        if self.serial_conn and getattr(self.serial_conn, 'is_open', False):
            try:
                self.serial_conn.close()
            except:
                pass
            self.serial_conn = None

        if self.tcp_sock:
            try:
                self.tcp_sock.close()
            except:
                pass
            self.tcp_sock = None

    def send_command(self, cmd):
        if not self.is_connected:
            return
        payload = f"{cmd}\r".encode('ascii')
        try:
            if self.conn_type == "SERIAL" and self.serial_conn and self.serial_conn.is_open:
                self.serial_conn.write(payload)
            elif self.conn_type == "TCP" and self.tcp_sock:
                self.tcp_sock.sendall(payload)
        except:
            pass

    def read_loop(self):
        buffer = b""
        while self.is_connected:
            try:
                data = b""
                if self.conn_type == "SERIAL":
                    if self.serial_conn and self.serial_conn.in_waiting > 0:
                        data = self.serial_conn.read(self.serial_conn.in_waiting)
                    else:
                        time.sleep(0.05)
                        continue
                elif self.conn_type == "TCP":
                    try:
                        data = self.tcp_sock.recv(1024)
                        if not data:
                            # Socket disconnected by remote peer
                            raise ConnectionResetError("Connection closed by WIZ750SR")
                    except socket.timeout:
                        continue

                if data:
                    # Filter rogue XON/XOFF control characters embedded by ISW8001
                    data = data.replace(b'\x11', b'').replace(b'\x13', b'')
                    buffer += data
                    
                    if b'\r' in buffer:
                        lines = buffer.split(b'\r')
                        buffer = lines[-1]
                        for line in lines[:-1]:
                            if line.strip():
                                if self.callback:
                                    self.callback(line.decode('ascii', errors='ignore').strip())
            except Exception as e:
                if self.is_connected and self.callback:
                    self.callback(f"Error: {e}")
                self.disconnect()
                break


# --- GUI Application ---
class DualPortGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("ISW8001 Dual Wattmeter Profiler (Serial & Ethernet WIZ750SR)")
        self.root.geometry("1140x820")
        
        style = ttk.Style()
        style.theme_use('clam')
        
        # --- Top Efficiency Banner ---
        eff_frame = tk.Frame(root, bg="#2C3E50", bd=5, relief=tk.RAISED)
        eff_frame.pack(fill=tk.X, padx=10, pady=(10, 5))
        
        self.var_efficiency = tk.StringVar(value="System Efficiency (P2 / P1) : --- %")
        tk.Label(eff_frame, textvariable=self.var_efficiency, 
                 font=("Consolas", 20, "bold"), fg="#F1C40F", bg="#2C3E50", pady=10).pack()

        # --- Main Split Layout ---
        main_frame = tk.Frame(root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.frame1 = tk.LabelFrame(main_frame, text="Port 1 (Input)", font=("Arial", 12, "bold"), padx=10, pady=10)
        self.frame1.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        self.frame2 = tk.LabelFrame(main_frame, text="Port 2 (Output)", font=("Arial", 12, "bold"), padx=10, pady=10)
        self.frame2.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        self.handlers = {1: None, 2: None}
        self.data_history = {1: collections.deque(maxlen=100), 2: collections.deque(maxlen=100)}
        self.latest_power = {1: 0.0, 2: 0.0}

        self.setup_port_ui(self.frame1, 1)
        self.setup_port_ui(self.frame2, 2)
        
        self.refresh_ports() # Initialize port lists

        self.ani = animation.FuncAnimation(self.fig1, self.update_charts, interval=500, cache_frame_data=False)

    def refresh_ports(self):
        ports = [port.device for port in serial.tools.list_ports.comports()]
        simulators = ["SIMULATOR-P1", "SIMULATOR-P2"]
        all_ports = ports + simulators
        
        for pid in [1, 2]:
            cb = getattr(self, f"port_cb_{pid}", None)
            if cb:
                current_val = cb.get()
                cb['values'] = all_ports
                if current_val in all_ports:
                    cb.set(current_val)
                elif all_ports:
                    default_idx = len(all_ports) - (3 - pid)
                    if 0 <= default_idx < len(all_ports):
                        cb.current(default_idx)

    def on_mode_change(self, port_id):
        mode = getattr(self, f"conn_mode_{port_id}").get()
        serial_frame = getattr(self, f"serial_frame_{port_id}")
        tcp_frame = getattr(self, f"tcp_frame_{port_id}")
        if mode == "ETHERNET (TCP)":
            serial_frame.pack_forget()
            tcp_frame.pack(side=tk.LEFT, padx=5)
        else:
            tcp_frame.pack_forget()
            serial_frame.pack(side=tk.LEFT, padx=5)

    def setup_port_ui(self, parent, port_id):
        # 1. Connection Controls (Serial vs Ethernet)
        conn_frame = tk.Frame(parent)
        conn_frame.pack(fill=tk.X, pady=(0, 10))

        # Mode selector
        mode_var = tk.StringVar(value="SERIAL (COM)" if port_id == 1 else "ETHERNET (TCP)")
        setattr(self, f"conn_mode_{port_id}", mode_var)
        
        mode_cb = ttk.Combobox(conn_frame, textvariable=mode_var, values=["SERIAL (COM)", "ETHERNET (TCP)"], width=14, state="readonly")
        mode_cb.pack(side=tk.LEFT)
        mode_cb.bind("<<ComboboxSelected>>", lambda e: self.on_mode_change(port_id))

        # Frame for Serial Controls
        serial_frame = tk.Frame(conn_frame)
        setattr(self, f"serial_frame_{port_id}", serial_frame)
        
        port_cb = ttk.Combobox(serial_frame, width=13, font=("Arial", 10))
        port_cb.pack(side=tk.LEFT, padx=2)
        setattr(self, f"port_cb_{port_id}", port_cb)
        
        btn_refresh = ttk.Button(serial_frame, text="↻", width=3, command=self.refresh_ports)
        btn_refresh.pack(side=tk.LEFT, padx=(0, 2))

        # Frame for TCP / Ethernet Controls
        tcp_frame = tk.Frame(conn_frame)
        setattr(self, f"tcp_frame_{port_id}", tcp_frame)
        
        tk.Label(tcp_frame, text="IP:Port", font=("Arial", 9)).pack(side=tk.LEFT)
        default_ip = "192.168.11.2:5000" if port_id == 2 else "192.168.11.3:5000"
        tcp_entry = ttk.Entry(tcp_frame, width=17, font=("Arial", 10))
        tcp_entry.insert(0, default_ip)
        tcp_entry.pack(side=tk.LEFT, padx=3)
        setattr(self, f"tcp_entry_{port_id}", tcp_entry)

        # Place initial frame based on default mode
        if mode_var.get() == "ETHERNET (TCP)":
            tcp_frame.pack(side=tk.LEFT, padx=5)
        else:
            serial_frame.pack(side=tk.LEFT, padx=5)

        # Connect button
        btn_connect = ttk.Button(conn_frame, text="Connect", command=lambda: self.toggle_connection(port_id))
        btn_connect.pack(side=tk.LEFT, padx=5)
        setattr(self, f"btn_connect_{port_id}", btn_connect)

        # 2. Device Controls
        ctrl_frame = tk.LabelFrame(parent, text="ISW8001 Controls", fg="#2980B9")
        ctrl_frame.pack(fill=tk.X, pady=5)
        
        func_frame = tk.Frame(ctrl_frame)
        func_frame.pack(fill=tk.X, pady=5, padx=5)
        tk.Label(func_frame, text="Mode:").pack(side=tk.LEFT, padx=(0, 10))
        for cmd in ["WATT", "VAR", "VOLT", "AMP", "PWF"]:
            ttk.Button(func_frame, text=cmd, width=6, command=lambda c=cmd: self.send_cmd(port_id, c)).pack(side=tk.LEFT, padx=2)
            
        range_frame = tk.Frame(ctrl_frame)
        range_frame.pack(fill=tk.X, pady=5, padx=5)
        tk.Label(range_frame, text="Range:").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(range_frame, text="AutoRange", command=lambda: self.send_cmd(port_id, "AUTORANGE")).pack(side=tk.LEFT, padx=2)
        ttk.Button(range_frame, text="Manual", command=lambda: self.send_cmd(port_id, "MANUAL")).pack(side=tk.LEFT, padx=2)

        # 3. Numeric Display
        data_frame = tk.Frame(parent, bg="#ECF0F1", bd=2, relief=tk.SUNKEN)
        data_frame.pack(fill=tk.X, pady=10)

        setattr(self, f"var_v_{port_id}", tk.StringVar(value="--- V"))
        setattr(self, f"var_i_{port_id}", tk.StringVar(value="--- A"))
        setattr(self, f"var_w_{port_id}", tk.StringVar(value="--- W"))

        tk.Label(data_frame, textvariable=getattr(self, f"var_v_{port_id}"), font=("Consolas", 16, "bold"), fg="#2980B9", bg="#ECF0F1", width=10).pack(side=tk.LEFT, expand=True, pady=10)
        tk.Label(data_frame, textvariable=getattr(self, f"var_i_{port_id}"), font=("Consolas", 16, "bold"), fg="#27AE60", bg="#ECF0F1", width=10).pack(side=tk.LEFT, expand=True, pady=10)
        tk.Label(data_frame, textvariable=getattr(self, f"var_w_{port_id}"), font=("Consolas", 16, "bold"), fg="#C0392B", bg="#ECF0F1", width=10).pack(side=tk.LEFT, expand=True, pady=10)

        # 4. Charting
        fig = Figure(figsize=(4, 3.5), dpi=100)
        fig.patch.set_facecolor('#F8F9F9')
        ax = fig.add_subplot(111)
        ax.set_title(f"Primary Reading (W/VAR/PF)", fontsize=10)
        ax.grid(True, linestyle='--', alpha=0.7)
        fig.tight_layout(pad=2.0)
        
        canvas = FigureCanvasTkAgg(fig, master=parent)
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, pady=5)
        
        setattr(self, f"fig_{port_id}", fig)
        setattr(self, f"ax_{port_id}", ax)
        setattr(self, f"canvas_{port_id}", canvas)
        if port_id == 1: self.fig1 = fig

        # 5. Raw Output
        tk.Label(parent, text="Raw Stream:", fg="#7F8C8D").pack(anchor="w")
        log_txt = scrolledtext.ScrolledText(parent, width=30, height=3, font=("Consolas", 9), bg="#Fdfdfd")
        log_txt.pack(fill=tk.X)
        setattr(self, f"log_txt_{port_id}", log_txt)

    def send_cmd(self, port_id, cmd):
        handler = self.handlers.get(port_id)
        if handler and handler.is_connected:
            handler.send_command(cmd)
        else:
            messagebox.showwarning("Not Connected", f"Connect to Port {port_id} first.")

    def toggle_connection(self, port_id):
        btn = getattr(self, f"btn_connect_{port_id}")
        mode = getattr(self, f"conn_mode_{port_id}").get()
        
        if btn["text"] == "Connect":
            if mode == "ETHERNET (TCP)":
                target = getattr(self, f"tcp_entry_{port_id}").get().strip()
                if not target:
                    messagebox.showerror("Error", "Please specify an IP:Port for WIZ750SR (e.g. 192.168.11.2:5000)")
                    return
                handler = ConnectionHandler("TCP", target)
            else:
                target = getattr(self, f"port_cb_{port_id}").get().strip()
                if not target:
                    messagebox.showerror("Error", "Please select a COM port")
                    return
                handler = ConnectionHandler("SERIAL", target)

            handler.callback = lambda data, pid=port_id: self.root.after(0, self.process_data, pid, data)
            
            success, msg = handler.connect()
            if success:
                self.handlers[port_id] = handler
                btn.config(text="Disconnect")
                self.data_history[port_id].clear()
                self.latest_power[port_id] = 0.0
                self.update_efficiency()
            else:
                messagebox.showerror("Connection Error", msg)
        else:
            handler = self.handlers.get(port_id)
            if handler:
                handler.disconnect()
                self.handlers[port_id] = None
            btn.config(text="Connect")
            
            getattr(self, f"var_v_{port_id}").set("--- V")
            getattr(self, f"var_i_{port_id}").set("--- A")
            getattr(self, f"var_w_{port_id}").set("--- W")
            self.data_history[port_id].clear()
            self.latest_power[port_id] = 0.0
            
            ax = getattr(self, f"ax_{port_id}")
            ax.clear()
            ax.set_title(f"Primary Reading (W/VAR/PF)", fontsize=10)
            ax.grid(True, linestyle='--', alpha=0.7)
            getattr(self, f"canvas_{port_id}").draw()
            self.update_efficiency()

    def process_data(self, port_id, data):
        log_txt = getattr(self, f"log_txt_{port_id}")
        log_txt.insert(tk.END, data + "\n")
        log_txt.see(tk.END)
        if float(log_txt.index('end-1c').split('.')[0]) > 20:
            log_txt.delete('1.0', '2.0')

        # Parse ISW8001 protocol
        v_match = re.search(r'U\d=([+-]?[\d\.]+E[+-]?\d+)', data)
        i_match = re.search(r'I\d=([+-]?[\d\.]+E[+-]?\d+)', data)
        w_match = re.search(r'W=([+-]?[\d\.]+E[+-]?\d+)', data)
        pf_match = re.search(r'PF=([+-]?[\d\.]+E[+-]?\d+)', data)
        var_match = re.search(r'VAR=([+-]?[\d\.]+E[+-]?\d+)', data)

        if v_match:
            try:
                val = float(v_match.group(1))
                getattr(self, f"var_v_{port_id}").set(f"{val:.2f} V")
            except: pass
            
        if i_match:
            try:
                val = float(i_match.group(1))
                getattr(self, f"var_i_{port_id}").set(f"{val:.3f} A")
            except: pass
            
        if w_match:
            try:
                val = float(w_match.group(1))
                getattr(self, f"var_w_{port_id}").set(f"{val:.2f} W")
                self.data_history[port_id].append(val)
                self.latest_power[port_id] = val
                self.update_efficiency()
            except: pass
        elif var_match:
            try:
                val = float(var_match.group(1))
                getattr(self, f"var_w_{port_id}").set(f"{val:.2f} VAR")
                self.data_history[port_id].append(val)
            except: pass
        elif pf_match:
            try:
                val = float(pf_match.group(1))
                getattr(self, f"var_w_{port_id}").set(f"{val:.3f} PF")
                self.data_history[port_id].append(val)
            except: pass
        elif "overflow" in data:
            getattr(self, f"var_w_{port_id}").set(f"OVERFLOW")

    def update_efficiency(self):
        p1 = self.latest_power.get(1, 0.0)
        p2 = self.latest_power.get(2, 0.0)
        
        if p1 > 0 and p2 >= 0:
            eff = (p2 / p1) * 100.0
            self.var_efficiency.set(f"System Efficiency (P2 / P1) : {eff:.2f} %")
        else:
            self.var_efficiency.set("System Efficiency (P2 / P1) : --- %")

    def update_charts(self, frame):
        for port_id in [1, 2]:
            if not self.handlers[port_id]:
                continue
                
            ax = getattr(self, f"ax_{port_id}")
            canvas = getattr(self, f"canvas_{port_id}")
            data = list(self.data_history[port_id])
            
            ax.clear()
            ax.set_title(f"Primary Reading (W/VAR/PF)", fontsize=10)
            ax.grid(True, linestyle='--', alpha=0.7)
            
            if data:
                color = '#C0392B' if port_id == 1 else '#E67E22'
                ax.plot(data, color=color, linewidth=2)
                min_y, max_y = min(data), max(data)
                pad = max(0.1, (max_y - min_y) * 0.1)
                ax.set_ylim(min_y - pad, max_y + pad)
            
            canvas.draw()

    def on_closing(self):
        for pid, handler in self.handlers.items():
            if handler:
                handler.disconnect()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = DualPortGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
