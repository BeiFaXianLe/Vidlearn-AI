"""S2 API 路由：探测、导入（获取媒体）、凭据管理、任务查询。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from apps.adapters import resolve_adapter
from apps.adapters.base import AcquireError, FetchOpts
from apps.adapters.bilibili import BilibiliAdapter
from apps.adapters.douyin import DouyinAdapter
from apps.core.acquire import AcquisitionManager
from apps.core.credentials import CredentialError, FileCredentialProvider
from apps.core.logging_setup import get_logger

router = APIRouter(prefix="/api", tags=["s2"])
log = get_logger("api")


def _state(request: Request):
    return request.app.state


def _cred(request: Request) -> FileCredentialProvider:
    st = _state(request)
    if not hasattr(st, "cred"):
        st.cred = FileCredentialProvider(st.settings.data_root / "credentials")
    return st.cred


class ProbeIn(BaseModel):
    source: str


class ImportIn(BaseModel):
    source: str
    max_height: int | None = None
    download_sections: str | None = None


class CookieIn(BaseModel):
    platform: str = "bilibili"
    raw: str


class VerifyIn(BaseModel):
    platform: str = "bilibili"


@router.post("/credentials/verify")
async def verify_credential(body: VerifyIn, request: Request):
    """检测某平台已保存的 Cookie 是否为有效登录态（B站真实校验；抖音做字段体检）。"""
    st = _state(request)
    p = _cred(request)
    if not p.get(body.platform):
        return {"ok": False, "platform": body.platform, "message": "未配置 Cookie"}
    try:
        if body.platform == "bilibili":
            ad = BilibiliAdapter(yt_dlp_path=st.settings.yt_dlp_path,
                                 ffprobe=st.settings.ffprobe_path,
                                 cookie_provider=p,
                                 cookie_tmp_dir=st.settings.media.temp / "cookies")
            r = await ad.verify_login()
            return {"platform": "bilibili", **r}
        if body.platform == "douyin":
            ad = DouyinAdapter(yt_dlp_path=st.settings.yt_dlp_path,
                               ffprobe=st.settings.ffprobe_path,
                               cookie_provider=p,
                               cookie_tmp_dir=st.settings.media.temp / "cookies",
                               cookies_from_browser=st.settings.ytdlp_cookies_from_browser,
                             douyin_use_browser=st.settings.douyin_use_browser,
                             douyin_browser_path=st.settings.douyin_browser_path)
            r = await ad.verify_login()
            return {"platform": "douyin", **r}
        return {"ok": False, "platform": body.platform, "message": "不支持的平台"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "platform": body.platform, "message": str(e)[:160]}


@router.post("/probe")
async def probe(body: ProbeIn, request: Request):
    st = _state(request)
    try:
        ad = resolve_adapter(body.source, yt_dlp=st.settings.yt_dlp_path,
                             ffprobe=st.settings.ffprobe_path, cookie_provider=_cred(request),
                             cookie_tmp_dir=st.settings.media.temp / "cookies",
                             cookies_from_browser=st.settings.ytdlp_cookies_from_browser,
                             douyin_use_browser=st.settings.douyin_use_browser,
                             douyin_browser_path=st.settings.douyin_browser_path)
        meta = await ad.probe(body.source)
        return {"ok": True, "meta": meta.__dict__}
    except AcquireError as e:
        return {"ok": False, "error": {"code": e.code.value, "message": e.message}}


@router.post("/import")
async def import_media(body: ImportIn, request: Request):
    st = _state(request)
    try:
        ad = resolve_adapter(body.source, yt_dlp=st.settings.yt_dlp_path,
                             ffprobe=st.settings.ffprobe_path, cookie_provider=_cred(request),
                             cookie_tmp_dir=st.settings.media.temp / "cookies",
                             cookies_from_browser=st.settings.ytdlp_cookies_from_browser,
                             douyin_use_browser=st.settings.douyin_use_browser,
                             douyin_browser_path=st.settings.douyin_browser_path)
        mgr = AcquisitionManager(st.settings.media.temp, st.settings.media.original, st.settings.ffmpeg_path)
        res = await mgr.acquire(ad, body.source, max_height=body.max_height,
                                download_sections=body.download_sections)
        return {"ok": True, "media": {
            "path": str(res.file_path), "sha256": res.sha256,
            "height": res.height, "width": res.width, "vcodec": res.vcodec,
            "acodec": res.acodec, "has_audio": res.has_audio,
            "duration_ms": res.declared_duration_ms,
        }}
    except AcquireError as e:
        return {"ok": False, "error": {"code": e.code.value, "message": e.message,
                                       "retryable": e.retryable}}


@router.post("/credentials")
async def set_credential(body: CookieIn, request: Request):
    try:
        p = _cred(request)
        p.set(body.platform, body.raw)
        return {"ok": True, "backend": p.backend, "status": p.status(body.platform)}
    except CredentialError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/credentials/{platform}")
async def get_credential_status(platform: str, request: Request):
    p = _cred(request)
    keys = list((p.get(platform) or {}).keys())
    return {"ok": True, "backend": p.backend, "status": p.status(platform), "keys": keys}


@router.delete("/credentials/{platform}")
async def clear_credential(platform: str, request: Request):
    p = _cred(request)
    p.clear(platform)
    return {"ok": True, "status": p.status(platform)}


# ---------------- B站收藏夹（登录态批量导入） ----------------
def _bili(request: Request) -> BilibiliAdapter:
    st = _state(request)
    return BilibiliAdapter(yt_dlp_path=st.settings.yt_dlp_path,
                           ffprobe=st.settings.ffprobe_path,
                           cookie_provider=_cred(request),
                           cookie_tmp_dir=st.settings.media.temp / "cookies")


@router.get("/bilibili/fav/folders")
async def bili_fav_folders(request: Request):
    """读取当前登录 B站账号的收藏夹文件夹列表。"""
    try:
        r = await _bili(request).fetch_fav_folders()
        return {"ok": True, **r}
    except AcquireError as e:
        return {"ok": False, "error": {"code": e.code.value, "message": e.message}}


@router.get("/bilibili/fav/items")
async def bili_fav_items(media_id: str, request: Request, page: int = 1, page_size: int = 20):
    """分页读取某收藏夹内的视频（返回 bvid，供批量导入复用）。"""
    page = max(1, page)
    page_size = max(1, min(page_size, 50))
    try:
        r = await _bili(request).fetch_fav_items(media_id, pn=page, ps=page_size)
        return {"ok": True, **r}
    except AcquireError as e:
        return {"ok": False, "error": {"code": e.code.value, "message": e.message}}


@router.get("/transcript/tracks")
async def transcript_tracks(source: str, request: Request):
    """获取平台字幕（B站）。返回轨道与选定结果的摘要，不含全文。"""
    st = _state(request)
    ad = resolve_adapter(source, yt_dlp=st.settings.yt_dlp_path,
                         ffprobe=st.settings.ffprobe_path, cookie_provider=_cred(request),
                             cookie_tmp_dir=st.settings.media.temp / "cookies",
                             cookies_from_browser=st.settings.ytdlp_cookies_from_browser,
                             douyin_use_browser=st.settings.douyin_use_browser,
                             douyin_browser_path=st.settings.douyin_browser_path)
    if not hasattr(ad, "fetch_subtitles"):
        raise HTTPException(status_code=400, detail="该来源不支持平台字幕")
    r = await ad.fetch_subtitles(source)
    c = r.get("chosen")
    return {"ok": bool(c), "tracks": len(r.get("tracks", [])),
            "chosen": None if not c else {
                "source": c["source"], "lang": c["lang"], "is_ai": c["is_ai"],
                "cues": len(c["cues"]), "coverage_ratio": c.get("coverage_ratio"),
                "first": c["cues"][0]["text"][:40] if c["cues"] else None,
            },
            "reason": r.get("reason")}

