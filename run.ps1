# VidLearn AI 启动脚本（Windows PowerShell）
# 用法：.\run.ps1  或双击 run.cmd
# 依赖：.venv 已创建并安装依赖；或先运行 .\setup.ps1

$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "未找到虚拟环境，请先执行: .\setup.ps1（或双击 setup.cmd）" -ForegroundColor Yellow
    exit 1
}

# --- ASR 模型定位（按优先级）---
# 1) 用户显式指定 VIDLEARN_ASR_MODEL_DIR（推荐：自己下载的模型目录）
if (-not $env:VIDLEARN_ASR_MODEL_DIR -and (Test-Path ".\models\faster-whisper-small")) {
    $env:VIDLEARN_ASR_MODEL_DIR = (Resolve-Path ".\models\faster-whisper-small").Path
}
# 2) 否则使用本地 HF 缓存（若存在）
if (-not $env:VIDLEARN_ASR_MODEL_DIR -and (Test-Path ".\.tmp\hf")) {
    $env:HF_HOME = (Resolve-Path ".\.tmp\hf").Path
}
if ($env:VIDLEARN_ASR_MODEL_DIR) {
    Write-Host "ASR 模型目录: $env:VIDLEARN_ASR_MODEL_DIR" -ForegroundColor Cyan
}

$port = if ($env:VIDLEARN_PORT) { $env:VIDLEARN_PORT } else { "8000" }
# 控制台 UTF-8，避免中文日志乱码
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
Write-Host "启动 VidLearn AI : http://127.0.0.1:$port" -ForegroundColor Green
& $py -m uvicorn apps.main:app --host 127.0.0.1 --port $port
