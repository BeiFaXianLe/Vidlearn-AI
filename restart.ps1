# VidLearn AI 重启脚本：先 stop 再 run
# 服务在当前窗口前台运行，关闭窗口即停止；需后台常驻请用计划任务/服务。
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

Write-Host "== 重启 VidLearn AI ==" -ForegroundColor Cyan
& "$PSScriptRoot\stop.ps1"
Start-Sleep -Milliseconds 800
& "$PSScriptRoot\run.ps1"
