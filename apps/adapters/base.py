"""视频来源适配器统一接口与数据模型（S2-01）。

对应 INTERFACE_CONTRACTS.md §1。所有下载器实现该 Protocol。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


class ErrorCode(str, enum.Enum):
    """统一错误码（INTERFACE_CONTRACTS §6）。"""

    NEED_LOGIN = "need_login"
    FORMAT_CHANGED = "format_changed"
    BLOCKED = "blocked"
    NOT_AUTHORIZED = "not_authorized"
    NETWORK = "network"
    MEDIA_INVALID = "media_invalid"
    MEDIA_NO_AUDIO = "media_no_audio"
    SUBTITLE_UNRELIABLE = "subtitle_unreliable"
    QUOTA = "quota"
    UNSUPPORTED_URL = "unsupported_url"
    INTERNAL = "internal"


class AcquireError(Exception):
    def __init__(self, code: ErrorCode, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass
class VideoMeta:
    platform: str
    platform_video_id: str
    title: str
    author: str | None = None
    duration_ms: int = 0
    cover_url: str | None = None
    available_heights: list[int] = field(default_factory=list)
    has_subtitle_tracks: bool = False
    source_url: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class FetchOpts:
    """下载选项。"""

    max_height: int | None = None       # None = 自动选最高可下
    prefer_codec: str = "avc1"          # 优先 H.264（浏览器兼容）
    audio_only: bool = False
    out_dir: Path | None = None
    timeout_sec: int = 900
    download_sections: str | None = None  # 如 "*0-15" 仅用于验证


@dataclass
class MediaResult:
    file_path: Path
    container: str
    sha256: str
    declared_duration_ms: int
    width: int | None = None
    height: int | None = None
    vcodec: str | None = None
    acodec: str | None = None
    has_audio: bool = True
    error_code: str | None = None


@runtime_checkable
class VideoAdapter(Protocol):
    name: str

    async def can_handle(self, url: str) -> bool: ...

    async def probe(self, url: str) -> VideoMeta: ...

    async def fetch_media(self, url: str, opts: FetchOpts) -> MediaResult: ...
