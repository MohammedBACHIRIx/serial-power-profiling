@echo off
title Dual Wattmeter Power Profiler
cd /d "%~dp0"

if exist "dist\DualWattmeterProfiler\DualWattmeterProfiler.exe" (
    start "" "dist\DualWattmeterProfiler\DualWattmeterProfiler.exe"
) else if exist "dist\ChargerPowerProfiler\ChargerPowerProfiler.exe" (
    start "" "dist\ChargerPowerProfiler\ChargerPowerProfiler.exe"
) else (
    start "" pythonw dual_wattmeter_gui.py
)
exit
