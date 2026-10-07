@echo off
REM One-click launch: starts the headless logger (hidden) then the GUI viewer.
REM Uses config\devices.json if present, otherwise config\devices.example.json.
cd /d "%~dp0"

echo Starting PowerProfiler logger...
start "PowerProfiler Logger" /min pythonw scripts\run_logger.pyw

REM give the logger a moment to register devices in the DB before the GUI reads it
timeout /t 3 /nobreak >nul

echo Starting PowerProfiler GUI...
start "PowerProfiler GUI" pythonw scripts\run_gui.pyw

exit /b 0
