import matplotlib
matplotlib.use('TkAgg')
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import time
from . import theme

class ChartManager:
    def __init__(self, parent):
        self.fig = Figure(figsize=(10, 6), dpi=100, facecolor=theme.CHART_BG)
        self.axes = []
        self.lines = []
        
        colors = [
            theme.ACCENT_GREEN, theme.ACCENT_BLUE, theme.ACCENT_YELLOW, theme.ACCENT_RED,
            '#FF9900', '#CC00FF', '#00FFFF', '#FF00FF'
        ]
        
        self.axes = []
        for i in range(8):
            kwargs = {}
            if i > 0:
                kwargs['sharex'] = self.axes[0]
            ax = self.fig.add_subplot(4, 2, i + 1, **kwargs)
            ax.set_facecolor(theme.CHART_BG)
            ax.tick_params(colors=theme.TEXT_DIM, labelsize=8)
            for spine in ax.spines.values():
                spine.set_color('#444')
            ax.grid(True, color='#333', linestyle='--')
            
            line, = ax.plot([], [], color=colors[i], linewidth=1.5)
            self.axes.append(ax)
            self.lines.append(line)
            
        self.fig.tight_layout()
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill='both', expand=True)
        
        self.bg_cache = [None] * 8
        self.visible = [True] * 8
        self.y_limits = [(0.0, 1.0)] * 8
        
        # We'll use a common 60s window
        self.window_s = 60.0
        self.last_xlim_update = 0
        self.common_xlim = (0, 1)
        self._initial_draw_done = False
        
    def toggle_visibility(self, idx, is_visible):
        if 0 <= idx < 8:
            self.visible[idx] = is_visible
            self.lines[idx].set_visible(is_visible)
            # Full redraw to update static background
            self.canvas.draw()
            for i, ax in enumerate(self.axes):
                self.bg_cache[i] = self.canvas.copy_from_bbox(ax.bbox)
            
    def _save_bg(self, idx=None):
        self.canvas.draw()
        if idx is None:
            for i, ax in enumerate(self.axes):
                self.bg_cache[i] = self.canvas.copy_from_bbox(ax.bbox)
        else:
            self.bg_cache[idx] = self.canvas.copy_from_bbox(self.axes[idx].bbox)
            
    def update_data(self, data_by_idx):
        """data_by_idx is a dict {idx: (times, values)}"""
        now = time.time()
        
        needs_full_redraw = False
        if not self._initial_draw_done:
            needs_full_redraw = True
            self._initial_draw_done = True
            
        # Update common X limits if time moved significantly
        if now - self.last_xlim_update > 0.5:
            self.common_xlim = (now - self.window_s, now)
            self.axes[0].set_xlim(self.common_xlim)
            self.last_xlim_update = now
            needs_full_redraw = True
            
        # Check Y limits for all active charts
        active_updates = {}
        for idx, (times, values) in data_by_idx.items():
            if not self.visible[idx]:
                continue
                
            # Filter to window
            cutoff = now - self.window_s
            valid_times = [t for t in times if t >= cutoff]
            valid_values = [v for t, v in zip(times, values) if t >= cutoff]
            
            if not valid_times:
                continue
                
            active_updates[idx] = (valid_times, valid_values)
            
            min_v = min(valid_values)
            max_v = max(valid_values)
            ymin, ymax = self.y_limits[idx]
            
            # Hysteresis for Y scale
            if min_v < ymin or max_v > ymax or (ymax - ymin > 0 and (max_v - min_v) / (ymax - ymin) < 0.2):
                margin = (max_v - min_v) * 0.1
                if margin == 0:
                    margin = 1.0
                self.y_limits[idx] = (min_v - margin, max_v + margin)
                self.axes[idx].set_ylim(self.y_limits[idx])
                needs_full_redraw = True
                
        if needs_full_redraw:
            self._save_bg()
            
        # Blit active updates
        for idx, (t, v) in active_updates.items():
            ax = self.axes[idx]
            line = self.lines[idx]
            line.set_data(t, v)
            if self.bg_cache[idx] is not None:
                self.canvas.restore_region(self.bg_cache[idx])
            ax.draw_artist(line)
            self.canvas.blit(ax.bbox)
            
        self.canvas.flush_events()
