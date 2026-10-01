import argparse
import sys
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import queue
import collections
import time
from typing import Dict, List, Any

from .. import storage, config
from ..protocol import FLAG_SPIKE
from . import theme
from .device_panel import DevicePanel
from .control import ControlPanel
from .charts import ChartManager

class PowerProfilerApp:
    def __init__(self, root: tk.Tk, db_path: str, numeric_only: bool):
        self.root = root
        self.db_path = db_path
        self.numeric_only = numeric_only
        
        self.root.title("ISW8001 Power Profiler")
        self.root.configure(bg=theme.BG_COLOR)
        theme.setup_styles()
        
        self.reader = storage.Reader(db_path)
        self.devices = self.reader.devices()
        
        if not self.devices:
            messagebox.showerror("Error", "No devices found in DB.")
            self.root.destroy()
            return
            
        self.device_ids = [d["id"] for d in self.devices]
        
        # State
        self.last_sample_ids = {d_id: 0 for d_id in self.device_ids}
        self.sample_queue = queue.Queue()
        self.health_queue = queue.Queue()
        self.alert_queue = queue.Queue()
        
        # Deques for data: 60 seconds * ~20 Hz = 1200, 5000 is safe
        self.times_d = {d_id: collections.deque(maxlen=5000) for d_id in self.device_ids}
        self.power_d = {d_id: collections.deque(maxlen=5000) for d_id in self.device_ids}
        self.last_ts = {d_id: 0.0 for d_id in self.device_ids}
        
        self.filter_spikes_var = tk.BooleanVar(value=True)
        
        self.panels = {}
        self.active_alert = None
        
        self._build_ui()
        
        self.poll_thread = threading.Thread(target=self._db_poll_worker, daemon=True)
        self.poll_thread.start()
        
        self.root.after(250, self._process_queue)
        if not self.numeric_only:
            self.root.after(500, self._redraw_charts)
            
    def _build_ui(self):
        # Top alerts/controls
        top_bar = ttk.Frame(self.root, style='TFrame')
        top_bar.pack(fill=tk.X, padx=5, pady=5)
        
        chk = tk.Checkbutton(top_bar, text="Filter Spikes", variable=self.filter_spikes_var, 
                             bg=theme.BG_COLOR, fg=theme.TEXT_COLOR, selectcolor=theme.PANEL_BG)
        chk.pack(side=tk.LEFT, padx=5)
        
        self.alert_frame = ttk.Frame(top_bar, style='Panel.TFrame')
        self.alert_label = tk.Label(self.alert_frame, text="", bg=theme.PANEL_BG, fg=theme.ACCENT_RED, font=("Arial", 12, "bold"))
        self.alert_label.pack(side=tk.LEFT, padx=5)
        self.ack_btn = ttk.Button(self.alert_frame, text="Acknowledge", command=self._ack_alert)
        self.ack_btn.pack(side=tk.LEFT, padx=5)
        # Hidden initially
        
        # Devices layout
        panels_frame = ttk.Frame(self.root, style='TFrame')
        panels_frame.pack(fill=tk.X, padx=5, pady=5)
        
        for i, d in enumerate(self.devices):
            d_id = d["id"]
            name = d["name"]
            color = theme.ACCENT_GREEN if i % 2 == 0 else theme.ACCENT_BLUE # Fallbacks
            
            f = ttk.Frame(panels_frame, style='TFrame')
            f.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
            
            dp = DevicePanel(f, name, color)
            dp.pack(fill=tk.X)
            
            cp = ControlPanel(f, self.db_path, d_id)
            cp.pack(fill=tk.X, pady=2)
            
            self.panels[d_id] = dp
            
        if not self.numeric_only:
            self.chart_mgr = ChartManager(self.root)
            # hide unused charts
            for i in range(8):
                if i >= len(self.devices):
                    self.chart_mgr.toggle_visibility(i, False)
                    
    def _ack_alert(self):
        if self.active_alert:
            storage.ack_alert(self.db_path, self.active_alert["id"])
            self.alert_frame.pack_forget()
            self.active_alert = None
            
    def _db_poll_worker(self):
        # We need a new reader for the thread
        local_reader = storage.Reader(self.db_path)
        while True:
            try:
                for d_id in self.device_ids:
                    samples = local_reader.samples_after(d_id, self.last_sample_ids[d_id], limit=5000)
                    if samples:
                        self.last_sample_ids[d_id] = samples[-1]["id"]
                        self.sample_queue.put((d_id, samples))
                        
                    health = local_reader.latest_health(d_id)
                    if health:
                        self.health_queue.put((d_id, health))
                        
                alerts = local_reader.unacked_alerts()
                if alerts:
                    self.alert_queue.put(alerts[0])
            except Exception as e:
                print(f"DB poll error: {e}")
                
            time.sleep(0.25)
            
    def _process_queue(self):
        filter_spikes = self.filter_spikes_var.get()
        now = time.time()
        
        # Health
        while not self.health_queue.empty():
            d_id, health = self.health_queue.get()
            is_stale = (now - self.last_ts[d_id]) > 5.0
            if d_id in self.panels:
                self.panels[d_id].update_health(health["state"], is_stale)
                
        # Also check staleness for all
        for d_id, panel in self.panels.items():
            if now - self.last_ts[d_id] > 5.0:
                panel.update_health("unknown", True)
                
        # Alerts
        while not self.alert_queue.empty():
            alert = self.alert_queue.get()
            if not self.active_alert or self.active_alert["id"] != alert["id"]:
                self.active_alert = alert
                self.alert_label.config(text=f"ALERT: {alert['message']}")
                self.alert_frame.pack(side=tk.RIGHT, padx=10)
                
        # Samples
        while not self.sample_queue.empty():
            d_id, samples = self.sample_queue.get()
            if not samples:
                continue
                
            # Update panel with latest valid sample
            last_valid = None
            for s in reversed(samples):
                if filter_spikes and (s["flags"] & FLAG_SPIKE):
                    continue
                last_valid = s
                break
                
            if last_valid:
                self.last_ts[d_id] = last_valid["ts"]
                self.panels[d_id].update_values(
                    last_valid.get("power_w"),
                    last_valid.get("voltage_v"),
                    last_valid.get("current_a"),
                    last_valid.get("pf"),
                    last_valid.get("energy_wh"),
                    last_valid.get("v_range"),
                    last_valid.get("i_range")
                )
                
            # Append to deque
            t_dq = self.times_d[d_id]
            p_dq = self.power_d[d_id]
            for s in samples:
                if filter_spikes and (s["flags"] & FLAG_SPIKE):
                    continue
                t_dq.append(s["ts"])
                if s.get("power_w") is not None:
                    p_dq.append(s["power_w"])
                else:
                    p_dq.append(0.0)
                    
        self.root.after(250, self._process_queue)
        
    def _redraw_charts(self):
        if not self.numeric_only and hasattr(self, 'chart_mgr'):
            data_by_idx = {}
            for i, d in enumerate(self.devices):
                d_id = d["id"]
                data_by_idx[i] = (list(self.times_d[d_id]), list(self.power_d[d_id]))
            self.chart_mgr.update_data(data_by_idx)
            
        self.root.after(500, self._redraw_charts)


def main(argv=None):
    parser = argparse.ArgumentParser(description="ISW8001 GUI Viewer")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--config", help="Path to JSON config file")
    group.add_argument("--db", help="Direct path to SQLite DB")
    parser.add_argument("--numeric-only", action="store_true", help="Skip charts")
    
    args = parser.parse_args(argv)
    
    if args.config:
        try:
            cfg = config.load(args.config)
            db_path = cfg.db_path
        except Exception as e:
            print(f"Error loading config: {e}")
            sys.exit(1)
    else:
        db_path = args.db
        
    root = tk.Tk()
    app = PowerProfilerApp(root, db_path, args.numeric_only)
    root.mainloop()

if __name__ == "__main__":
    main()
