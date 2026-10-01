import tkinter as tk
from tkinter import ttk
from . import theme

class DevicePanel(ttk.LabelFrame):
    def __init__(self, parent, name, color, **kwargs):
        super().__init__(parent, text=name, padding=5, **kwargs)
        self.color = color
        
        self.power_var = tk.StringVar(value="0.00 W")
        self.volt_var = tk.StringVar(value="0.0 V")
        self.curr_var = tk.StringVar(value="0.0 A")
        self.pf_var = tk.StringVar(value="0.00")
        self.energy_var = tk.StringVar(value="0.0 Wh")
        
        self.v_range_var = tk.StringVar(value="")
        self.i_range_var = tk.StringVar(value="")
        
        self.health_var = tk.StringVar(value="⚫") # dot
        self.health_color = theme.TEXT_DIM
        
        self._build_ui()
        
    def _build_ui(self):
        # Health row
        health_frame = ttk.Frame(self, style='Panel.TFrame')
        health_frame.pack(fill=tk.X, pady=2)
        
        self.health_label = tk.Label(health_frame, textvariable=self.health_var, font=("Arial", 12), bg=theme.PANEL_BG, fg=self.health_color)
        self.health_label.pack(side=tk.RIGHT, padx=5)
        
        # Power Readout
        tk.Label(self, textvariable=self.power_var, font=("Consolas", 32, "bold"), bg=theme.PANEL_BG, fg=self.color).pack(fill=tk.X, pady=10)
        
        # Stats Grid
        grid = ttk.Frame(self, style='Panel.TFrame')
        grid.pack(fill=tk.X, pady=2)
        
        self._add_grid_row(grid, 0, "Voltage:", self.volt_var, self.v_range_var)
        self._add_grid_row(grid, 1, "Current:", self.curr_var, self.i_range_var)
        self._add_grid_row(grid, 2, "P.Factor:", self.pf_var, None)
        self._add_grid_row(grid, 3, "Energy:", self.energy_var, None)
        
    def _add_grid_row(self, parent, row, label_text, var, range_var):
        ttk.Label(parent, text=label_text, style='Panel.TLabel', font=("Arial", 11)).grid(row=row, column=0, sticky=tk.W, pady=2, padx=5)
        ttk.Label(parent, textvariable=var, style='Panel.TLabel', font=("Consolas", 12, "bold")).grid(row=row, column=1, sticky=tk.E, pady=2, padx=5)
        if range_var:
            ttk.Label(parent, textvariable=range_var, style='Panel.TLabel', font=("Arial", 9), foreground=theme.TEXT_DIM).grid(row=row, column=2, sticky=tk.W, pady=2, padx=(5, 0))
        parent.columnconfigure(1, weight=1)
        
    def update_values(self, power, voltage, current, pf, energy, v_range, i_range):
        if power is not None:
            self.power_var.set(f"{power:.2f} W")
        if voltage is not None:
            self.volt_var.set(f"{voltage:.2f} V")
        if current is not None:
            if current < 1.0 and current > -1.0:
                self.curr_var.set(f"{current * 1000.0:.1f} mA")
            else:
                self.curr_var.set(f"{current:.3f} A")
        if pf is not None:
            self.pf_var.set(f"{pf:.2f}")
        if energy is not None:
            self.energy_var.set(f"{energy:.3f} Wh")
            
        if v_range:
            self.v_range_var.set(f"[{v_range}]")
        if i_range:
            self.i_range_var.set(f"[{i_range}]")
            
    def update_health(self, state, is_stale):
        if is_stale:
            self.health_var.set("⚫")
            self.health_label.configure(fg=theme.TEXT_DIM)
        elif state == "ok":
            self.health_var.set("🟢")
            self.health_label.configure(fg=theme.ACCENT_GREEN)
        elif state == "error":
            self.health_var.set("🔴")
            self.health_label.configure(fg=theme.ACCENT_RED)
        else:
            self.health_var.set("🟡")
            self.health_label.configure(fg=theme.ACCENT_YELLOW)
