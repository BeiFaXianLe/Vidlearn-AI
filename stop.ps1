# VidLearn AI 停止脚本（Windows PowerShell）
# 用法：.\stop.ps1   （默认端口 8000，可用 -Port 或环境变量 VIDLEARN_PORT 覆盖）
# 或直接双击 stop.cmd
param([int]$Port = 0)
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

if (-not $Port -or $Port -le 0) {
    $Port = if ($env:VIDLEARN_PORT) { [int]$env:VIDLEARN_PORT } else { 8000 }
}

Write-Host "== 停止 VidLearn AI（端口 $Port）==" -ForegroundColor Cyan

function Get-ListenerPids([int]$p) {
    $result = @()
    try {
        $conns = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction Stop
        $result = @($conns | Select-Object -ExpandProperty OwningProcess -Unique)
    } catch {
        # 回退：解析 netstat
        $lines = netstat -ano | Select-String "LISTENING" | Where-Object { $_.Line -match (":$p\s") }
        foreach ($l in $lines) {
            $cols = @(($l.Line -split '\s+') | Where-Object { $_ -ne '' })
            if ($cols.Count -ge 5) { $result += [int]$cols[-1] }
        }
    }
    return @($result | Where-Object { $_ -gt 0 } | Select-Object -Unique)
}

$found = $false
foreach ($procId in (Get-ListenerPids $Port)) {
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if (-not $proc) { continue }
    if ($proc.ProcessName -notmatch '^python') {
        Write-Host ("  端口 {0} 被非 Python 进程占用（{1}, PID {2}），已跳过以免误杀" -f $Port, $proc.ProcessName, $procId) -ForegroundColor Yellow
        continue
    }
    $found = $true
    Write-Host ("  结束 {0} (PID {1}) 及其子进程 ..." -f $proc.ProcessName, $procId)
    # /T 一并结束 yt-dlp / ffmpeg 等子进程
    taskkill /PID $procId /T /F 2>&1 | Out-Null
}
Start-Sleep -Milliseconds 800

$left = @(Get-ListenerPids $Port)
if ($left.Count -gt 0) {
    Write-Host ("  端口 {0} 仍被占用（PID: {1}），请重试或以管理员身份运行" -f $Port, ($left -join ',')) -ForegroundColor Yellow
} elseif ($found) {
    Write-Host "  已停止。" -ForegroundColor Green
} else {
    Write-Host ("  未在端口 {0} 找到运行中的服务（可能本来就没启动）。" -f $Port) -ForegroundColor Yellow
}
