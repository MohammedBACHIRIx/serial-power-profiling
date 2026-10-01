import tkinter as tk
from tkinter import ttk
from .. import storage

class ControlPanel(ttk.Frame):
    def __init__(self, parent, db_path, device_id, **kwargs):
        super().__init__(parent, style='TFrame', **kwargs)
        self.db_path = db_path
        self.device_id = device_id
        self._build_ui()
        
    def _send(self, cmd):
        storage.send_command(self.db_path, self.device_id, cmd)
        
    def _build_ui(self):
        row1 = ttk.Frame(self, style='TFrame')
        row1.pack(fill=tk.X, pady=2)
        ttk.Button(row1, text="WATT", width=4, command=lambda: self._send("WATT")).pack(side=tk.LEFT, padx=1)
        ttk.Button(row1, text="VOLT", width=4, command=lambda: self._send("VOLT")).pack(side=tk.LEFT, padx=1)
        ttk.Button(row1, text="AMP", width=4, command=lambda: self._send("AMP")).pack(side=tk.LEFT, padx=1)
        ttk.Button(row1, text="PWF", width=4, command=lambda: self._send("PWF")).pack(side=tk.LEFT, padx=1)
        ttk.Button(row1, text="MA1", width=4, command=lambda: self._send("MA1")).pack(side=tk.LEFT, padx=1)
        ttk.Button(row1, text="MA0", width=4, command=lambda: self._send("MA0")).pack(side=tk.LEFT, padx=1)
        
        row2 = ttk.Frame(self, style='TFrame')
        row2.pack(fill=tk.X, pady=2)
        ttk.Button(row2, text="Auto R", width=6, command=lambda: self._send("AUTORANGE")).pack(side=tk.LEFT, padx=1)
        ttk.Button(row2, text="Manual R", width=8, command=lambda: self._send("MANUAL")).pack(side=tk.LEFT, padx=1)
        
        row3 = ttk.Frame(self, style='TFrame')
        row3.pack(fill=tk.X, pady=2)
        ttk.Button(row3, text="U1", width=3, command=lambda: self._send("SET:U1")).pack(side=tk.LEFT, padx=1)
        ttk.Button(row3, text="U2", width=3, command=lambda: self._send("SET:U2")).pack(side=tk.LEFT, padx=1)
        ttk.Button(row3, text="U3", width=3, command=lambda: self._send("SET:U3")).pack(side=tk.LEFT, padx=1)
        ttk.Button(row3, text="I1", width=3, command=lambda: self._send("SET:I1")).pack(side=tk.LEFT, padx=1)
        ttk.Button(row3, text="I2", width=3, command=lambda: self._send("SET:I2")).pack(side=tk.LEFT, padx=1)
        ttk.Button(row3, text="I3", width=3, command=lambda: self._send("SET:I3")).pack(side=tk.LEFT, padx=1)
