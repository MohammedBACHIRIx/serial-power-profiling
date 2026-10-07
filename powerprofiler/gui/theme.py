import tkinter as tk
from tkinter import ttk

# Theme Colors
BG_COLOR = '#1E1E24'
PANEL_BG = '#2b2b36'
TEXT_COLOR = '#E0E0E0'
TEXT_DIM = '#A0A0A0'
ACCENT_GREEN = '#00FF9D'
ACCENT_BLUE = '#00B8FF'
ACCENT_YELLOW = '#FFD700'
ACCENT_RED = '#FF6B81'  # WCAG AA (>=4.5:1) on both BG and PANEL; alert text must stay legible
CHART_BG = '#1E1E24'

def setup_styles():
    style = ttk.Style()
    if 'clam' in style.theme_names():
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
