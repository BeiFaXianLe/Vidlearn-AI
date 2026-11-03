# VidLearn AI 安装脚本（Windows PowerShell）
# 若提示执行策略：powershell -ExecutionPolicy Bypass -File .\setup.ps1  或直接双击 setup.cmd
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

Write-Host "== 1. 创建 Python 3.12 虚拟环境 ==" -ForegroundColor Cyan
if (-not (Test-Path ".venv")) {
    if (Have "uv") {
        uv venv .venv --python 3.12 2>&1 | Out-Null
    } else {
        if (Have "py") { py -3.12 -m venv .venv } else { python -m venv .venv }
    }
} else {
    Write-Host "  .venv 已存在，跳过" -ForegroundColor Green
}

Write-Host "== 2. 安装后端依赖 ==" -ForegroundColor Cyan
$pydeps = @("fastapi","uvicorn[standard]","pydantic","pydantic-settings","python-multipart","pyyaml","httpx","faster-whisper>=1.2,<1.3","opencc-python-reimplemented","cryptography","pypinyin","pytest","pytest-asyncio")
if (Have "uv") {
    uv pip install --python ".\.venv\Scripts\python.exe" @pydeps 2>&1 | Out-Null
} else {
    & ".\.venv\Scripts\python.exe" -m pip install --upgrade pip 2>&1 | Out-Null
    & ".\.venv\Scripts\python.exe" -m pip install @pydeps 2>&1 | Out-Null
}
if ($LASTEXITCODE -ne 0) { Write-Host "  依赖安装可能有告警，请检查" -ForegroundColor Yellow }
else { Write-Host "  后端依赖就绪" -ForegroundColor Green }

Write-Host "== 3. 前端构建（可选；已带 dist 可跳过）==" -ForegroundColor Cyan
if (Test-Path (Join-Path $PSScriptRoot "apps\web\package.json")) {
    Push-Location (Join-Path $PSScriptRoot "apps\web")
    if (Have "pnpm") {
        $env:CI = "true"
        & pnpm install --config.confirmModulesPurge=false 2>&1 | Out-Null
        if (Test-Path "node_modules\vite\bin\vite.js") {
            & node node_modules\vite\bin\vite.js build 2>&1 | Out-Null
            Write-Host "  前端构建完成" -ForegroundColor Green
        }
    } else {
        Write-Host "  未安装 pnpm，跳过前端构建（使用已存在的 dist）" -ForegroundColor Yellow
    }
    Pop-Location
}

Write-Host "== 4. 检查外部工具 ==" -ForegroundColor Cyan
foreach ($t in @("ffmpeg","ffprobe","yt-dlp")) {
    $p = Get-Command $t -ErrorAction SilentlyContinue
    if ($p) { Write-Host "  OK $t -> $($p.Source)" -ForegroundColor Green }
    else { Write-Host "  缺失 $t（请安装并加入 PATH；yt-dlp 可用 uv tool install yt-dlp）" -ForegroundColor Yellow }
}

Write-Host "== 5. 检查 ASR 模型 ==" -ForegroundColor Cyan
$modelPath = Join-Path $PSScriptRoot "models\faster-whisper-small\model.bin"
if (Test-Path $modelPath) {
    Write-Host "  OK 模型已存在 models\faster-whisper-small" -ForegroundColor Green
} else {
    Write-Host "  未找到模型，首次运行会尝试下载；慢的话见 docs\MODEL_SETUP.md" -ForegroundColor Yellow
}

Write-Host "== 完成。运行 run.cmd（或 .\run.ps1）启动 ==" -ForegroundColor Green
