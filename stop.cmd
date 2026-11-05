@echo off
REM VidLearn AI stop entry (bypass PowerShell execution policy)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
echo.
pause
