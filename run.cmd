@echo off
REM VidLearn AI 启动入口（免 PowerShell 执行策略限制）
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
pause
