"""适配器包：来源识别与工厂（S2）。"""
from __future__ import annotations

from apps.adapters.base import (
    AcquireError,
    ErrorCode,
    FetchOpts,
    MediaResult,
    VideoAdapter,
    VideoMeta,
)
from apps.adapters.bilibili import BilibiliAdapter
from apps.adapters.douyin import DouyinAdapter
from apps.adapters.local_file import LocalFileAdapter

__all__ = [
    "AcquireError", "ErrorCode", "FetchOpts", "MediaResult", "VideoAdapter", "VideoMeta",
    "BilibiliAdapter", "DouyinAdapter", "LocalFileAdapter", "resolve_adapter",
]


def resolve_adapter(source: str, *, yt_dlp: str = "yt-dlp", ffprobe: str = "ffprobe",
                    cookie_provider=None, cookie_tmp_dir=None,
                    cookies_from_browser: str = "") -> VideoAdapter:
    """按来源返回适配器。source 可为本地路径或 URL。"""
    s = (source or "").strip()
    if "bilibili.com" in s or s.upper().startswith("BV") or "/video/BV" in s:
        return BilibiliAdapter(yt_dlp_path=yt_dlp, ffprobe=ffprobe,
                               cookie_provider=cookie_provider,
                               cookie_tmp_dir=cookie_tmp_dir)
    if "douyin.com" in s or "iesdouyin.com" in s:
        return DouyinAdapter(yt_dlp_path=yt_dlp, ffprobe=ffprobe,
                             cookie_provider=cookie_provider,
                             cookie_tmp_dir=cookie_tmp_dir,
                             cookies_from_browser=cookies_from_browser)
    # 其它平台暂不支持
    from pathlib import Path
    if Path(s).exists():
        return LocalFileAdapter(ffprobe=ffprobe)
    raise AcquireError(ErrorCode.UNSUPPORTED_URL, f"暂不支持的来源: {s[:80]}")
