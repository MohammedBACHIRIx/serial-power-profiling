@echo off
title AC/DC Charger Power & Efficiency Profiler
cd /d "%~dp0"

if exist "dist\ChargerPowerProfiler\ChargerPowerProfiler.exe" (
    start "" "dist\ChargerPowerProfiler\ChargerPowerProfiler.exe"
) else (
    start "" pythonw dual_wattmeter_gui.py
)
exit
