#!/usr/bin/env bash
# VidLearn AI — Linux 安装脚本
# 用法： bash deploy/setup.sh
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
echo "== 项目目录: $ROOT =="

# ---------- 1) Python 3.12 ----------
PY="${PYTHON:-python3.12}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "!! 未找到 python3.12。请安装：sudo apt install python3.12 python3.12-venv"
  echo "   (或设置 PYTHON=python3.11 后重试)"
  exit 1
fi
echo "== Python: $($PY --version) =="

# ---------- 2) 依赖 ----------
DEPS=(
  "fastapi" "uvicorn[standard]" "pydantic" "pydantic-settings"
  "python-multipart" "pyyaml" "httpx"
  "faster-whisper>=1.2,<1.3" "opencc-python-reimplemented" "cryptography"
  "pytest" "pytest-asyncio"
)

if [ ! -d .venv ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv .venv --python 3.12
  else
    "$PY" -m venv .venv
  fi
fi

if command -v uv >/dev/null 2>&1; then
  uv pip install --python .venv/bin/python "${DEPS[@]}"
else
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install "${DEPS[@]}"
fi
echo "== 后端依赖已安装 =="

# ---------- 3) 前端构建 ----------
if [ -f apps/web/package.json ]; then
  if command -v pnpm >/dev/null 2>&1; then
    ( cd apps/web && pnpm install --config.confirmModulesPurge=false && node node_modules/vite/bin/vite.js build )
    echo "== 前端构建完成 =="
  elif command -v npm >/dev/null 2>&1; then
    ( cd apps/web && npm install && node node_modules/vite/bin/vite.js build )
    echo "== 前端构建完成（npm） =="
  else
    echo "!! 未找到 pnpm/npm，跳过前端构建（需要 Node 18+）"
  fi
fi

# ---------- 4) 外部工具 ----------
for t in ffmpeg ffprobe yt-dlp; do
  if command -v "$t" >/dev/null 2>&1; then
    echo "  OK  $t -> $(command -v "$t")"
  else
    echo "  缺失 $t（apt install ffmpeg；yt-dlp 可 pipx install yt-dlp 或 uv tool install yt-dlp）"
  fi
done

# ---------- 5) 模型 ----------
if [ -f models/faster-whisper-small/model.bin ]; then
  echo "  OK  ASR 模型已存在 models/faster-whisper-small"
else
  echo "  未找到模型；首次运行会下载（约 464MB），慢可用镜像，见 docs/v2/MODEL_SETUP.md"
fi

# ---------- 6) 配置 ----------
if [ ! -f .env ]; then
  cp .env.example .env
  echo "  已生成 .env（请填写 VIDLEARN_LLM_API_KEY）"
fi

echo "== 完成。启动： bash deploy/run.sh =="
