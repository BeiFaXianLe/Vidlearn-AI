# VidLearn AI — Linux 镜像
# 多阶段：前端构建 → 运行镜像
FROM node:20-slim AS web
WORKDIR /web
COPY apps/web/package.json apps/web/pnpm-lock.yaml* apps/web/pnpm-workspace.yaml* /web/
RUN corepack enable && (pnpm install --config.confirmModulesPurge=false || npm install)
COPY apps/web /web
RUN (node node_modules/vite/bin/vite.js build) || (npx vite build)

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PYTHONIOENCODING=utf-8 \
    VIDLEARN_DATA_ROOT=/app/data

# 系统依赖：FFmpeg（含 ffprobe）、curl 供 yt-dlp 使用
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp（固定版本，避免自更新导致的不稳定）
RUN pip install --no-cache-dir "yt-dlp==2026.10.26"

WORKDIR /app
COPY pyproject.toml /app/
RUN pip install --no-cache-dir \
        "fastapi>=0.115" "uvicorn[standard]>=0.30" "pydantic>=2.9" \
        "pydantic-settings>=2.4" "python-multipart>=0.0.9" "pyyaml>=6.0" \
        "httpx>=0.27" "faster-whisper>=1.2.0,<1.3" \
        "opencc-python-reimplemented>=0.1.7" "cryptography>=42"

COPY apps /app/apps
COPY scripts /app/scripts
COPY .env.example /app/.env.example
COPY --from=web /web/dist /app/apps/web/dist

# 运行用户（非 root）
RUN useradd -m -u 10001 vidlearn && mkdir -p /app/data && chown -R vidlearn:vidlearn /app
USER vidlearn

EXPOSE 8000
VOLUME ["/app/data"]
# 模型建议挂载： -v ./models:/app/models 并设置 VIDLEARN_ASR_MODEL_DIR
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["python", "-m", "uvicorn", "apps.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
