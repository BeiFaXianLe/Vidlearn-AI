"""FastAPI 应用入口（S1 骨架）。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps.core.config import check_environment, load_settings
from apps.core.logging_setup import get_logger, setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    setup_logging(settings.media.logs)
    settings.media.ensure()
    log = get_logger("app")
    env = check_environment(settings)
    app.state.settings = settings
    app.state.env_check = env

    # 初始化数据库（单连接 + 写锁，供同步路由线程池安全使用）
    import threading
    from apps.core.jobs import JobStore
    from apps.storage import init_db
    app.state.db = init_db(settings.data_root / "database" / "vidlearn.db")
    app.state.db_lock = threading.RLock()
    app.state.jobs = JobStore(conn=app.state.db, db_lock=app.state.db_lock)

    # 清理历史遗留的 Cookie 临时文件（凭证安全：绝不能长期留在磁盘）
    try:
        from apps.adapters.bilibili import BilibiliAdapter
        from apps.core.acquire import purge_stale_job_dirs
        purge_stale_job_dirs(settings.media.temp)
        n = BilibiliAdapter.purge_stale_cookie_files(settings.media.temp / "cookies", 0)
        if n:
            log.info("已清理遗留 Cookie 临时文件: %d 个", n)
    except Exception:
        pass

    log.info("启动: env=%s data_root=%s 自检=%s", settings.env, settings.data_root, env["ok"])
    if not env["ok"]:
        for c in env["checks"]:
            if not c["ok"]:
                log.warning("自检失败: %s -> %s", c["name"], c["detail"])
    yield


app = FastAPI(title="VidLearn AI", version="0.1.0", lifespan=lifespan)

from apps.api_s2 import router as s2_router  # noqa: E402
from apps.api_s3 import router as s3_router  # noqa: E402
from apps.api_s4 import router as s4_router  # noqa: E402
from apps.api_s5 import router as s5_router  # noqa: E402
from apps.api_s5_punct import router as s5_punct_router  # noqa: E402
from apps.api_s6_media import router as s6_meta_router  # noqa: E402
from apps.api_s7 import router as s7_router  # noqa: E402
from apps.api_v2_ext import router as v2_ext_router  # noqa: E402

app.include_router(s2_router)
app.include_router(s3_router)
app.include_router(s4_router)
app.include_router(s5_router)
app.include_router(s5_punct_router)
app.include_router(s6_meta_router)
app.include_router(s7_router)
app.include_router(v2_ext_router)


@app.get("/api/health")
def health() -> dict:
    settings = getattr(app.state, "settings", None)
    env = getattr(app.state, "env_check", None)
    return {
        "status": "ok",
        "env": settings.env if settings else None,
        "data_root": str(settings.data_root) if settings else None,
        "environment": env,
    }


# ---- 前端静态资源（构建产物 apps/web/dist；存在才挂载）----
from pathlib import Path as _Path  # noqa: E402

_WEB_DIST = _Path(__file__).resolve().parent / "web" / "dist"
if _WEB_DIST.exists():
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    app.mount("/assets", StaticFiles(directory=str(_WEB_DIST / "assets")), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(_WEB_DIST / "index.html"))
