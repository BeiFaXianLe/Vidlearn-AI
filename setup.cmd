@echo off
REM VidLearn AI 安装入口（免 PowerShell 执行策略限制）
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
echo.
pause
