@echo off
REM VidLearn AI restart entry (bypass PowerShell execution policy)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart.ps1"
echo.
pause
