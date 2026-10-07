@echo off
title Power Profiler Web IDE Launcher
echo ======================================================================
echo    Starting Power Profiler Web IDE (Arduino Online Style)
echo    Opening browser at http://localhost:8000 ...
echo ======================================================================
start http://localhost:8000
python web_server.py
pause
