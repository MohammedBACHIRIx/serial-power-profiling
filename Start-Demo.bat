@echo off
REM One-click DEMO launch (no hardware needed): synthetic meters -> logger -> GUI.
REM Uses config\devices.demo.json (3 Demo devices, separate demo DB).
cd /d "%~dp0"

echo Starting PowerProfiler DEMO logger (synthetic data)...
start "PowerProfiler Demo Logger" /min pythonw -m powerprofiler.logger_app --config "config\devices.demo.json"

timeout /t 3 /nobreak >nul

echo Starting PowerProfiler GUI...
start "PowerProfiler Demo GUI" pythonw -m powerprofiler.gui.app --config "config\devices.demo.json"

exit /b 0
