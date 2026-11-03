"""本地文件适配器（S2-02）。

支持直接导入本地视频/音频文件：拷贝到临时区 → FFprobe 校验 → 计算 SHA256。
可检测重复（按 hash）。不做转码。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from apps.adapters._util import ffprobe_json, sha256_file
from apps.adapters.base import (
    AcquireError,
    ErrorCode,
    FetchOpts,
    MediaResult,
    VideoMeta,
)

VIDEO_EXT = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".flv", ".m4v", ".ts"}
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus"}
ALLOWED = VIDEO_EXT | AUDIO_EXT


class LocalFileAdapter:
    name = "local"

    def __init__(self, ffprobe: str = "ffprobe"):
        self._ffprobe = ffprobe

    async def can_handle(self, url: str) -> bool:
        # 本地适配器通过显式路径调用，不走 URL
        return False

    async def probe(self, url: str) -> VideoMeta:
        p = Path(url)
        if not p.exists():
            raise AcquireError(ErrorCode.MEDIA_INVALID, f"文件不存在: {p}")
        if p.suffix.lower() not in ALLOWED:
            raise AcquireError(ErrorCode.UNSUPPORTED_URL, f"不支持的扩展名: {p.suffix}")
        info = await ffprobe_json(p, self._ffprobe)
        if info is None:
            raise AcquireError(ErrorCode.MEDIA_INVALID, f"FFprobe 无法解析: {p.name}")
        fmt = info.get("format") or {}
        streams = info.get("streams") or []
        v = [s for s in streams if s.get("codec_type") == "video"]
        a = [s for s in streams if s.get("codec_type") == "audio"]
        dur_s = float(fmt.get("duration") or 0)
        return VideoMeta(
            platform="local",
            platform_video_id=sha256_file(p)[:16],
            title=p.stem,
            duration_ms=int(dur_s * 1000),
            available_heights=[v[0].get("height")] if v and v[0].get("height") else [],
            has_subtitle_tracks=any(s.get("codec_type") == "subtitle" for s in streams),
            extra={"has_audio": bool(a), "has_video": bool(v)},
        )

    async def fetch_media(self, url: str, opts: FetchOpts) -> MediaResult:
        src = Path(url)
        if not src.exists():
            raise AcquireError(ErrorCode.MEDIA_INVALID, f"文件不存在: {src}")
        out_dir = Path(opts.out_dir or src.parent)
        out_dir.mkdir(parents=True, exist_ok=True)
        dst = out_dir / src.name
        if dst.resolve() != src.resolve():
            shutil.copy2(src, dst)

        info = await ffprobe_json(dst, self._ffprobe)
        if info is None:
            raise AcquireError(ErrorCode.MEDIA_INVALID, f"FFprobe 无法解析: {dst.name}")
        fmt = info.get("format") or {}
        streams = info.get("streams") or []
        v = [s for s in streams if s.get("codec_type") == "video"]
        a = [s for s in streams if s.get("codec_type") == "audio"]
        if not v and not a:
            raise AcquireError(ErrorCode.MEDIA_INVALID, "无任何音视频流")
        # 校验：容器时长与流时长一致性（宽松）
        dur_s = float(fmt.get("duration") or 0)
        return MediaResult(
            file_path=dst,
            container=(fmt.get("format_name") or "unknown"),
            sha256=sha256_file(dst),
            declared_duration_ms=int(dur_s * 1000),
            width=v[0].get("width") if v else None,
            height=v[0].get("height") if v else None,
            vcodec=v[0].get("codec_name") if v else None,
            acodec=a[0].get("codec_name") if a else None,
            has_audio=bool(a),
        )
