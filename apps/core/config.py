"""VidLearn AI 配置管理（S1-02）。

- 支持 YAML 配置文件 + 环境变量覆盖（前缀 VIDLEARN_）
- 校验数据根目录、FFmpeg/yt-dlp 可执行文件
- 不在此处保存任何密钥明文
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class MediaDirs(BaseModel):
    """媒体目录结构（S1-08）。所有路径均相对 data_root。"""

    original: Path
    temp: Path
    audio_work: Path
    subtitles: Path
    thumbnails: Path
    keyframes: Path
    exports: Path
    database: Path
    logs: Path

    @classmethod
    def under(cls, root: Path) -> "MediaDirs":
        return cls(
            original=root / "media" / "original",
            temp=root / "media" / "temp",
            audio_work=root / "media" / "audio_work",
            subtitles=root / "media" / "subtitles",
            thumbnails=root / "media" / "thumbnails",
            keyframes=root / "media" / "keyframes",
            exports=root / "exports",
            database=root / "database",
            logs=root / "logs",
        )

    def ensure(self) -> None:
        for p in self.model_dump().values():
            Path(p).mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VIDLEARN_",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "VidLearn AI"
    env: Literal["dev", "prod"] = "dev"

    # 数据根目录
    data_root: Path = Field(default=PROJECT_ROOT / "data")

    # 外部工具
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    yt_dlp_path: str = "yt-dlp"
    # 从浏览器读取 Cookie 传给 yt-dlp（抖音等需要新鲜 Cookie 时用）
    # 取值如 chrome / edge / firefox / brave，留空则不用
    ytdlp_cookies_from_browser: str = ""
    # 抖音：优先用浏览器解析通道（免 Cookie；需 playwright + 本机 Chrome/Edge）
    douyin_use_browser: bool = True
    douyin_browser_path: str = ""     # 空=自动探测；也可指定 chrome/edge 可执行路径
    # 抖音 CDP：采集 Cookie 的浏览器调试端口（9222 常被占用，默认 9333）
    douyin_cdp_port: int = 9333
    # 抖音登录态 profile 目录（空=默认 data/browsers/douyin；扫码登录一次长期复用）
    douyin_profile_dir: str = ""

    # ASR
    asr_model: str = "small"
    asr_model_dir: str = ""          # 若指定，则直接作为本地模型目录（优先于 asr_model）
    asr_device: str = "cpu"
    asr_compute_type: str = "int8"
    asr_segment_sec: int = 30
    asr_overlap_sec: int = 2

    # 媒体
    max_upload_mb: int = 4096
    max_duration_min: int = 240

    # 下载：并发与单次超时（批量导入排队串行，避免多路抢带宽 + 900s 硬超时死循环）
    download_concurrency: int = 1
    download_timeout_sec: int = 3600
    download_stall_timeout_sec: int = 120   # 下载“无字节增长”多久判为假死并重连

    # 字幕安全阈值（S0 实测：末条不得超过视频时长 + 容差）
    subtitle_duration_tolerance_ms: int = 2000
    subtitle_refetch_attempts: int = 3

    # 云端 LLM（仅文本；密钥从环境变量 VIDLEARN_LLM_API_KEY 读取，不入仓库）
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"

    @field_validator("data_root")
    @classmethod
    def _abs(cls, v: Path) -> Path:
        return Path(v).expanduser().resolve()

    @property
    def media(self) -> MediaDirs:
        return MediaDirs.under(self.data_root)


def load_settings() -> Settings:
    return Settings()


def check_environment(settings: Settings) -> dict:
    """S1-01 环境自检：返回检查项与结果，不抛异常。"""
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    import sys

    add("python>=3.12,<3.13", (3, 12) <= sys.version_info[:2] < (3, 13), sys.version.split()[0])

    for tool, attr in (("ffmpeg", "ffmpeg_path"), ("ffprobe", "ffprobe_path"), ("yt-dlp", "yt_dlp_path")):
        path = getattr(settings, attr)
        resolved = shutil.which(path) or (path if Path(path).exists() else None)
        add(tool, bool(resolved), str(resolved or "NOT FOUND"))

    add("data_root_writable", True if _ensure_writable(settings.data_root) else False,
        str(settings.data_root))
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def _ensure_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False
