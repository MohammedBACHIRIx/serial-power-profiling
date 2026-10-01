import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import serial
import serial.tools.list_ports
import matplotlib
matplotlib.use('TkAgg')
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import threading
import queue
import time
import datetime
import math
import csv
import json
import random
import collections

# Theme Colors
BG_COLOR = '#1E1E24'
PANEL_BG = '#2b2b36'
TEXT_COLOR = '#E0E0E0'
TEXT_DIM = '#A0A0A0'
ACCENT_GREEN = '#00FF9D'
ACCENT_BLUE = '#00B8FF'
ACCENT_YELLOW = '#FFD700'
ACCENT_RED = '#FF3366'
CHART_BG = '#1E1E24'

class WattmeterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Dual ISW8001 / MPM-1010 Power Profiler")
        self.root.geometry("1200x850")
        self.root.configure(bg=BG_COLOR)
        
        self.buffer_size = 100000
        self.app_start_time = time.time()
        
        # Dual State
        self.serial_ports = [None, None]
        self.is_connected = [False, False]
        self.read_threads = [None, None]
        self.queues = [queue.Queue(), queue.Queue()]
        self.demo_times = [0.0, 0.0]
        
        # Latest Readings
        self.latest_power = [0.0, 0.0]
        self.total_energy_wh = [0.0, 0.0]
        self.last_meas_time = [None, None]
        
        # Chart Data Arrays
        self.time_data = collections.deque(maxlen=self.buffer_size)
        self.p_in_data = collections.deque(maxlen=self.buffer_size)
        self.p_out_data = collections.deque(maxlen=self.buffer_size)
        self.eff_data = collections.deque(maxlen=self.buffer_size)
        
        self.is_recording = False
        self.recorded_data = [] 
        
        # UI Variables
        self.port_cbs = [None, None]
        self.baud_cbs = [None, None]
        self.device_cbs = [None, None]
        self.sample_cbs = [None, None]
        self.connect_btns = [None, None]
        
        self.power_vars = [tk.StringVar(value="0.00 W"), tk.StringVar(value="0.00 W")]
        self.volt_vars = [tk.StringVar(value="0.0 V"), tk.StringVar(value="0.0 V")]
        self.curr_vars = [tk.StringVar(value="0.0 mA"), tk.StringVar(value="0.0 mA")]
        self.pf_vars = [tk.StringVar(value="0.00"), tk.StringVar(value="0.00")]
        self.energy_vars = [tk.StringVar(value="0.0 mWh"), tk.StringVar(value="0.0 mWh")]
        self.eff_var = tk.StringVar(value="0.0 %")
        
        self.setup_styles()
        self.build_ui()
        
        self.update_gui_loop()
        self.update_chart_loop()
        
    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background=BG_COLOR)
        style.configure('Panel.TFrame', background=PANEL_BG)
        style.configure('TLabel', background=BG_COLOR, foreground=TEXT_COLOR)
        style.configure('Panel.TLabel', background=PANEL_BG, foreground=TEXT_COLOR)
        style.configure('TButton', background='#3a3a4a', foreground=TEXT_COLOR, borderwidth=0, padding=5)
        style.map('TButton', background=[('active', '#4a4a5a'), ('pressed', '#2a2a3a')])
        style.configure('TCombobox', fieldbackground='#3a3a4a', background='#3a3a4a', foreground=TEXT_COLOR)
        style.map('TCombobox', fieldbackground=[('readonly', '#3a3a4a')])
        style.configure('TLabelframe', background=PANEL_BG, foreground=TEXT_COLOR)
        style.configure('TLabelframe.Label', background=PANEL_BG, foreground=TEXT_DIM)
        
    def build_ui(self):
        # Top half: Two meters side-by-side
        top_frame = ttk.Frame(self.root, style='TFrame')
        top_frame.pack(fill=tk.X, expand=False, padx=5, pady=5)
        
        meter1_frame = ttk.LabelFrame(top_frame, text="METER 1 (INPUT)", padding=5)
        meter1_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        self.build_meter_panel(meter1_frame, 0, ACCENT_GREEN)
        
        meter2_frame = ttk.LabelFrame(top_frame, text="METER 2 (OUTPUT)", padding=5)
        meter2_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))
        self.build_meter_panel(meter2_frame, 1, ACCENT_BLUE)
        
        # Center Efficiency & Global Controls
        eff_frame = ttk.Frame(self.root, style='Panel.TFrame')
        eff_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(eff_frame, text="SYSTEM EFFICIENCY:", style='Panel.TLabel', font=("Arial", 14, "bold")).pack(side=tk.LEFT, padx=10, pady=10)
        tk.Label(eff_frame, textvariable=self.eff_var, font=("Consolas", 24, "bold"), bg=PANEL_BG, fg=ACCENT_YELLOW).pack(side=tk.LEFT, padx=10)
        
        global_ctrl = ttk.Frame(eff_frame, style='Panel.TFrame')
        global_ctrl.pack(side=tk.RIGHT, padx=10, pady=10)
        self.rec_btn = tk.Button(global_ctrl, text="START RECORDING", bg='#3a3a4a', fg=TEXT_COLOR, command=self.toggle_recording, relief=tk.FLAT, padx=10)
        self.rec_btn.pack(side=tk.LEFT, padx=5)
        ttk.Button(global_ctrl, text="Clear Data", command=self.clear_data).pack(side=tk.LEFT, padx=5)
        ttk.Button(global_ctrl, text="Export CSV", command=self.export_csv).pack(side=tk.LEFT, padx=5)
        ttk.Button(global_ctrl, text="Export JSON", command=self.export_json).pack(side=tk.LEFT, padx=5)
        
        # Chart Frame
        chart_frame = ttk.Frame(self.root, style='Panel.TFrame')
        chart_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.fig = Figure(figsize=(10, 3), dpi=100, facecolor=CHART_BG)
        self.ax1 = self.fig.add_subplot(111)
        self.ax2 = self.ax1.twinx()
        
        self.ax1.set_facecolor(CHART_BG)
        self.ax1.tick_params(colors=TEXT_DIM)
        self.ax2.tick_params(colors=ACCENT_YELLOW)
        for ax in [self.ax1, self.ax2]:
            for spine in ax.spines.values():
                spine.set_color('#444')
                
        self.line_in, = self.ax1.plot([], [], color=ACCENT_GREEN, linewidth=1.5, label='Input (W)')
        self.line_out, = self.ax1.plot([], [], color=ACCENT_BLUE, linewidth=1.5, label='Output (W)')
        self.line_eff, = self.ax2.plot([], [], color=ACCENT_YELLOW, linewidth=1.2, linestyle='--', label='Efficiency (%)')
        
        self.ax1.set_ylabel('Power (W)', color=TEXT_DIM)
        self.ax2.set_ylabel('Efficiency (%)', color=ACCENT_YELLOW)
        self.ax1.grid(True, color='#333', linestyle='--')
        
        self.fig.legend(loc='upper left', bbox_to_anchor=(0.0, 1.0), facecolor=PANEL_BG, labelcolor=TEXT_COLOR)
        self.fig.tight_layout()
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        # Log
        log_frame = ttk.LabelFrame(self.root, text="Serial Log", padding=5)
        log_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=5, pady=5)
        self.log_txt = scrolledtext.ScrolledText(log_frame, height=5, bg='#1a1a20', fg='#a0a0b0', font=("Consolas", 9), borderwidth=0)
        self.log_txt.pack(fill=tk.X)
        
        self.scan_ports()

    def build_meter_panel(self, parent, idx, color):
        # Connection Row 1
        conn1 = ttk.Frame(parent, style='TFrame')
        conn1.pack(fill=tk.X, pady=2)
        ttk.Label(conn1, text="COM:", width=5).pack(side=tk.LEFT)
        self.port_cbs[idx] = ttk.Combobox(conn1, width=10, state="readonly")
        self.port_cbs[idx].pack(side=tk.LEFT, padx=2)
        ttk.Button(conn1, text="R", width=2, command=self.scan_ports).pack(side=tk.LEFT, padx=2)
        
        ttk.Label(conn1, text="Baud:", width=5).pack(side=tk.LEFT, padx=(5,0))
        self.baud_cbs[idx] = ttk.Combobox(conn1, values=["1200", "4800", "9600", "19200", "38400", "57600", "115200"], width=8, state="readonly")
        self.baud_cbs[idx].set("9600")
        self.baud_cbs[idx].pack(side=tk.LEFT, padx=2)
        
        # Connection Row 2
        conn2 = ttk.Frame(parent, style='TFrame')
        conn2.pack(fill=tk.X, pady=2)
        ttk.Label(conn2, text="Type:", width=5).pack(side=tk.LEFT)
        self.device_cbs[idx] = ttk.Combobox(conn2, values=["ISW8001", "MPM1010", "Demo"], width=10, state="readonly")
        self.device_cbs[idx].set("ISW8001")
        self.device_cbs[idx].pack(side=tk.LEFT, padx=2)
        
        ttk.Label(conn2, text="ms:", width=5).pack(side=tk.LEFT, padx=(5,0))
        self.sample_cbs[idx] = ttk.Combobox(conn2, values=["100", "200", "470", "1000", "2000"], width=8)
        self.sample_cbs[idx].set("470")
        self.sample_cbs[idx].pack(side=tk.LEFT, padx=2)
        
        self.connect_btns[idx] = tk.Button(conn2, text="CONNECT", bg='#3a3a4a', fg=color, command=lambda: self.toggle_connection(idx))
        self.connect_btns[idx].pack(side=tk.RIGHT, padx=2)
        
        # Power Readout
        tk.Label(parent, textvariable=self.power_vars[idx], font=("Consolas", 32, "bold"), bg=PANEL_BG, fg=color).pack(fill=tk.X, pady=10)
        
        # Stats Grid
        grid = ttk.Frame(parent, style='Panel.TFrame')
        grid.pack(fill=tk.X, pady=2)
        self.add_grid_row(grid, 0, "Voltage:", self.volt_vars[idx])
        self.add_grid_row(grid, 1, "Current:", self.curr_vars[idx])
        self.add_grid_row(grid, 2, "P.Factor:", self.pf_vars[idx])
        self.add_grid_row(grid, 3, "Energy:", self.energy_vars[idx])
        
        # Controls
        ctrl = ttk.Frame(parent, style='TFrame')
        ctrl.pack(fill=tk.X, pady=5)
        ttk.Button(ctrl, text="W", width=4, command=lambda: self.send_cmd(idx, "WATT")).grid(row=0, column=0, padx=1, pady=1)
        ttk.Button(ctrl, text="V", width=4, command=lambda: self.send_cmd(idx, "VOLT")).grid(row=0, column=1, padx=1, pady=1)
        ttk.Button(ctrl, text="A", width=4, command=lambda: self.send_cmd(idx, "AMP")).grid(row=0, column=2, padx=1, pady=1)
        ttk.Button(ctrl, text="MA1", width=5, command=lambda: self.send_cmd(idx, "MA1")).grid(row=0, column=3, padx=1, pady=1)
        ttk.Button(ctrl, text="MA0", width=5, command=lambda: self.send_cmd(idx, "MA0")).grid(row=0, column=4, padx=1, pady=1)
        
        ttk.Button(ctrl, text="Auto R", width=6, command=lambda: self.send_cmd(idx, "AUTORANGE")).grid(row=1, column=0, columnspan=2, sticky="ew", padx=1, pady=1)
        ttk.Button(ctrl, text="Manual R", width=6, command=lambda: self.send_cmd(idx, "MANUAL")).grid(row=1, column=2, columnspan=3, sticky="ew", padx=1, pady=1)

    def add_grid_row(self, parent, row, label_text, var):
        ttk.Label(parent, text=label_text, style='Panel.TLabel', font=("Arial", 11)).grid(row=row, column=0, sticky=tk.W, pady=2, padx=5)
        ttk.Label(parent, textvariable=var, style='Panel.TLabel', font=("Consolas", 12, "bold")).grid(row=row, column=1, sticky=tk.E, pady=2, padx=5)
        parent.columnconfigure(1, weight=1)
        
    def log(self, prefix, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_txt.insert(tk.END, f"[{ts}] {prefix}: {msg}\n")
        self.log_txt.see(tk.END)
        lines = int(self.log_txt.index('end-1c').split('.')[0])
        if lines > 500:
            self.log_txt.delete('1.0', f'{lines-400}.0')

    def scan_ports(self):
        ports = serial.tools.list_ports.comports()
        port_list = [p.device for p in ports]
        for i in range(2):
            self.port_cbs[i]['values'] = port_list
            if port_list and not self.port_cbs[i].get():
                self.port_cbs[i].set(port_list[0])

    def toggle_connection(self, idx):
        if self.is_connected[idx]:
            self.disconnect(idx)
        else:
            self.connect(idx)

    def connect(self, idx):
        port = self.port_cbs[idx].get()
        baud = int(self.baud_cbs[idx].get())
        device = self.device_cbs[idx].get()
        
        if device != "Demo" and not port:
            messagebox.showerror("Error", f"No COM port selected for Meter {idx+1}.")
            return
            
        try:
            if device != "Demo":
                self.serial_ports[idx] = serial.Serial(port, baud, timeout=0.1, xonxoff=True)
            
            self.is_connected[idx] = True
            color = ACCENT_RED
            self.connect_btns[idx].config(text="DISCONNECT", fg=color)
            self.port_cbs[idx].config(state="disabled")
            self.baud_cbs[idx].config(state="disabled")
            self.device_cbs[idx].config(state="disabled")
            self.log(f"SYS{idx+1}", f"Connected via {device}")
            
            self.last_meas_time[idx] = time.time()
            
            self.read_threads[idx] = threading.Thread(target=self.serial_read_loop, args=(idx,), daemon=True)
            self.read_threads[idx].start()
            
            if device == "ISW8001":
                try: sample_interval = int(self.sample_cbs[idx].get())
                except ValueError: sample_interval = 470
                if sample_interval == 470:
                    self.send_cmd(idx, "MA1")
                else:
                    self.send_cmd(idx, "MA0")
                    self.poll_device(idx)
            
        except Exception as e:
            messagebox.showerror(f"Meter {idx+1} Error", str(e))
            self.log(f"ERR{idx+1}", str(e))

    def disconnect(self, idx):
        self.is_connected[idx] = False
        if self.serial_ports[idx] and self.serial_ports[idx].is_open:
            self.serial_ports[idx].close()
        self.serial_ports[idx] = None
        
        color = ACCENT_GREEN if idx == 0 else ACCENT_BLUE
        self.connect_btns[idx].config(text="CONNECT", fg=color)
        self.port_cbs[idx].config(state="readonly")
        self.baud_cbs[idx].config(state="readonly")
        self.device_cbs[idx].config(state="readonly")
        self.log(f"SYS{idx+1}", "Disconnected")

    def poll_device(self, idx):
        if not self.is_connected[idx] or self.device_cbs[idx].get() != "ISW8001":
            return
        try: sample_interval = int(self.sample_cbs[idx].get())
        except ValueError: sample_interval = 470
        if sample_interval != 470:
            self.send_cmd(idx, "WATT")
            self.root.after(sample_interval, lambda: self.poll_device(idx))

    def send_cmd(self, idx, cmd):
        if not cmd: return
        self.log(f"TX{idx+1}", cmd)
        if self.is_connected[idx] and self.serial_ports[idx] and self.serial_ports[idx].is_open:
            try:
                self.serial_ports[idx].write((cmd + '\r').encode('ascii'))
            except Exception as e:
                self.log(f"ERR{idx+1}", f"Send failed: {e}")

    def serial_read_loop(self, idx):
        buffer = bytearray()
        while self.is_connected[idx]:
            try:
                if self.device_cbs[idx].get() == "Demo":
                    try: sample_interval = float(self.sample_cbs[idx].get()) / 1000.0
                    except ValueError: sample_interval = 0.47
                    time.sleep(sample_interval)
                    self.demo_times[idx] += sample_interval
                    
                    # Generate somewhat dependent loads for realism
                    # Meter 0 is input, Meter 1 is output
                    base_w = 50.0 + math.sin(self.demo_times[idx]) * 10.0
                    
                    if idx == 0:
                        w = base_w + random.random() * 2
                        v = 230.0 + math.sin(self.demo_times[idx] * 0.1) * 2.0
                    else:
                        # Output efficiency is around 85% to 92%
                        w = (base_w * 0.88) + random.random() * 2
                        v = 12.0 + random.random() * 0.1
                        
                    i = w / v
                    pf = 0.95 + random.random() * 0.04
                    line = f"U3={v:.1f}E+0 I1={i:.4f}E+0 W={w:.3f}E+0 PF={pf:.2f}"
                    self.queues[idx].put(('RX', line))
                    continue
                    
                if self.serial_ports[idx] and self.serial_ports[idx].is_open:
                    if self.serial_ports[idx].in_waiting > 0:
                        data = self.serial_ports[idx].read(self.serial_ports[idx].in_waiting)
                        for b in data:
                            if b in (0x11, 0x13): continue # Filter XON/XOFF
                            if b == 0x0D: # CR
                                line = buffer.decode('ascii', errors='ignore').strip()
                                buffer.clear()
                                if line: self.queues[idx].put(('RX', line))
                            elif b != 0x0A:
                                buffer.append(b)
                    else:
                        time.sleep(0.01)
            except Exception as e:
                self.queues[idx].put(('ERR', str(e)))
                break

    def update_gui_loop(self):
        updated = False
        for idx in range(2):
            try:
                while not self.queues[idx].empty():
                    msg_type, data = self.queues[idx].get_nowait()
                    if msg_type == 'RX':
                        self.log(f'RX{idx+1}', data)
                        self.parse_data(idx, data)
                        updated = True
                    elif msg_type == 'ERR':
                        self.log(f'ERR{idx+1}', data)
                        self.disconnect(idx)
            except queue.Empty:
                pass
                
        if updated:
            self.update_global_metrics()
            
        self.root.after(50, self.update_gui_loop)

    def parse_data(self, idx, line):
        now = time.time()
        parsed = {}
        parts = line.split()
        for p in parts:
            if '=' in p:
                k, v_str = p.split('=', 1)
                try:
                    if 'E' in v_str: val = float(v_str)
                    elif v_str.lower() == 'overflow': val = float('nan')
                    else: val = float(v_str)
                    parsed[k] = val
                except ValueError:
                    parsed[k] = v_str
                    
        w = None; v = None; i = None; pf = None
        for k, val in parsed.items():
            if k == 'W': w = val
            elif k in ('U1', 'U2', 'U3', 'V'): v = val
            elif k in ('I1', 'I2', 'I3', 'A'): i = val
            elif k == 'PF': pf = val

        if w is not None:
            self.latest_power[idx] = w
            if abs(w) < 1.0: self.power_vars[idx].set(f"{w*1000:.1f} mW")
            else: self.power_vars[idx].set(f"{w:.3f} W")
                
            if self.last_meas_time[idx]:
                dt_hours = (now - self.last_meas_time[idx]) / 3600.0
                self.total_energy_wh[idx] += w * dt_hours
            self.last_meas_time[idx] = now
            
            e_wh = self.total_energy_wh[idx]
            if e_wh < 1.0: self.energy_vars[idx].set(f"{e_wh*1000:.2f} mWh")
            else: self.energy_vars[idx].set(f"{e_wh:.4f} Wh")
            
        if v is not None: self.volt_vars[idx].set(f"{v:.1f} V")
        if i is not None:
            if abs(i) < 1.0: self.curr_vars[idx].set(f"{i*1000:.1f} mA")
            else: self.curr_vars[idx].set(f"{i:.3f} A")
        if pf is not None:
            if isinstance(pf, float) and math.isnan(pf): self.pf_vars[idx].set("Ovf")
            else: self.pf_vars[idx].set(f"{pf:.3f}")

    def update_global_metrics(self):
        # Called when any meter updates
        elapsed = time.time() - self.app_start_time
        p_in = self.latest_power[0]
        p_out = self.latest_power[1]
        
        eff = 0.0
        if p_in > 0.1: # Threshold to avoid noisy huge percentages
            eff = (p_out / p_in) * 100.0
            if eff > 200.0: eff = 200.0 # Clamp for chart visibility
            
        self.time_data.append(elapsed)
        self.p_in_data.append(p_in)
        self.p_out_data.append(p_out)
        self.eff_data.append(eff)
        
        self.eff_var.set(f"{eff:.1f} %")
        
        if self.is_recording:
            self.recorded_data.append({
                'time': elapsed,
                'power_in': p_in,
                'power_out': p_out,
                'efficiency': eff
            })

    def update_chart_loop(self):
        if len(self.time_data) > 1:
            current_time = self.time_data[-1]
            min_time = max(0, current_time - 60)
            
            # Simple slicing (deque doesn't support direct slicing easily, but we can list it)
            td = list(self.time_data)
            pin = list(self.p_in_data)
            pout = list(self.p_out_data)
            eff = list(self.eff_data)
            
            # Find start index
            idx = 0
            for i, t in enumerate(td):
                if t >= min_time:
                    idx = i
                    break
                    
            plot_t = td[idx:]
            if plot_t:
                self.line_in.set_data(plot_t, pin[idx:])
                self.line_out.set_data(plot_t, pout[idx:])
                self.line_eff.set_data(plot_t, eff[idx:])
                
                self.ax1.set_xlim(min_time, current_time + 1)
                
                max_p = max(max(pin[idx:]), max(pout[idx:]))
                margin = max_p * 0.1 if max_p > 0 else 1.0
                self.ax1.set_ylim(-margin, max_p + margin)
                
                self.ax2.set_ylim(0, 110) # 0 to 110% for efficiency is usually good
                
                self.canvas.draw_idle()
                
        self.root.after(500, self.update_chart_loop)

    def toggle_recording(self):
        if self.is_recording:
            self.is_recording = False
            self.rec_btn.config(text="START RECORDING", bg='#3a3a4a', fg=TEXT_COLOR)
            self.log("SYS", f"Recording stopped. {len(self.recorded_data)} samples saved.")
        else:
            self.is_recording = True
            self.rec_btn.config(text="STOP RECORDING", bg='#5a2a2a', fg=ACCENT_RED)
            self.log("SYS", "Recording started.")

    def clear_data(self):
        self.time_data.clear()
        self.p_in_data.clear()
        self.p_out_data.clear()
        self.eff_data.clear()
        self.recorded_data.clear()
        
        for i in range(2):
            self.latest_power[i] = 0.0
            self.total_energy_wh[i] = 0.0
            self.power_vars[i].set("0.00 W")
            self.energy_vars[i].set("0.0 mWh")
            
        self.eff_var.set("0.0 %")
        
        self.line_in.set_data([], [])
        self.line_out.set_data([], [])
        self.line_eff.set_data([], [])
        self.canvas.draw_idle()
        self.log("SYS", "Data cleared.")

    def export_csv(self):
        if not self.recorded_data: return messagebox.showinfo("Export", "No data to export.")
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path: return
        try:
            with open(path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['time', 'power_in', 'power_out', 'efficiency'])
                writer.writeheader()
                writer.writerows(self.recorded_data)
            self.log("SYS", f"Exported {len(self.recorded_data)} samples to CSV.")
        except Exception as e: messagebox.showerror("Export Error", str(e))

    def export_json(self):
        if not self.recorded_data: return messagebox.showinfo("Export", "No data to export.")
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path: return
        try:
            times = [d['time'] for d in self.recorded_data]
            p_in = [d['power_in'] for d in self.recorded_data]
            p_out = [d['power_out'] for d in self.recorded_data]
            
            profile = {
              "meta": { "version": 28, "startTime": 0, "product": "Dual Wattmeter", "categories": [{"name": "Power", "color": "green", "subcategories": ["In", "Out"]}] },
              "counters": [
                { "name": "Power In (W)", "category": "Power", "pid": 0, "mainThreadIndex": 0, "sampleGroups": [{ "id": 0, "samples": { "length": len(times), "time": times, "number": p_in } }] },
                { "name": "Power Out (W)", "category": "Power", "pid": 0, "mainThreadIndex": 0, "sampleGroups": [{ "id": 1, "samples": { "length": len(times), "time": times, "number": p_out } }] }
              ]
            }
            with open(path, 'w') as f: json.dump(profile, f)
            self.log("SYS", "Exported JSON Profiler data.")
        except Exception as e: messagebox.showerror("Export Error", str(e))

if __name__ == "__main__":
    root = tk.Tk()
    app = WattmeterApp(root)
    root.mainloop()
