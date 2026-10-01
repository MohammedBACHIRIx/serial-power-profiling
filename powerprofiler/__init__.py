"""Industrial multi-device ISW8001 power profiler.

Package layout:
    protocol.py   - pure framing/parsing/classification (no I/O)
    device.py     - DeviceWorker: one thread per serial port
    supervisor.py - DeviceSupervisor: owns N workers, reconnect/health
    storage.py    - SQLite schema, batched Writer, read-only Reader
    config.py     - JSON config load/validate/save
    alerts.py     - threshold evaluation + debounce (logger side)
    export.py     - CSV + Firefox-Profiler JSON export from the DB
    demo.py       - synthetic ISW8001 source for hardware-free testing
    logger_app.py - headless entry point
    gui/          - tkinter live viewer onto the DB
"""

__version__ = "0.1.0"
