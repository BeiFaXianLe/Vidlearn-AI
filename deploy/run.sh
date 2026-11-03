#!/usr/bin/env bash
# VidLearn AI — Linux 启动脚本
# 用法： bash deploy/run.sh            （默认 127.0.0.1:8000）
#       HOST=0.0.0.0 PORT=8000 bash deploy/run.sh
set -euo pipefail

cd "$(dirname "$0")/.."

PY=".venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "!! 未找到虚拟环境，请先执行： bash deploy/setup.sh"
  exit 1
fi

# ASR 模型目录（若使用项目内模型）
if [ -z "${VIDLEARN_ASR_MODEL_DIR:-}" ] && [ -d models/faster-whisper-small ]; then
  export VIDLEARN_ASR_MODEL_DIR="$(pwd)/models/faster-whisper-small"
  echo "ASR 模型目录: $VIDLEARN_ASR_MODEL_DIR"
fi

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
WORKERS="${WORKERS:-1}"
# 注意：本项目使用 SQLite 单连接 + 进程内任务表，必须单 worker；
# 多 worker 会导致任务状态/写锁不一致。扩容请纵向扩展或改用独立任务队列。
if [ "$WORKERS" != "1" ]; then
  echo "!! WORKERS=$WORKERS 不被支持（SQLite + 进程内任务表要求单 worker），已强制为 1"
  WORKERS=1
fi

echo "启动 VidLearn AI : http://${HOST}:${PORT}"
exec "$PY" -m uvicorn apps.main:app --host "$HOST" --port "$PORT" --workers "$WORKERS"
