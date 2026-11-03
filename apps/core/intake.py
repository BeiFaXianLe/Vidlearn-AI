"""媒体入库与字幕入库编排（S3）。

调用链：
  probe → media_assets(校验后 verified) → 选择字幕来源 → source_captions → transcript_segments
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from apps.adapters.base import MediaResult, VideoMeta
from apps.storage.repositories import (
    MediaAssetRepo,
    SegmentRepo,
    SourceCaptionRepo,
    VideoRepo,
)

SOURCE_PRIORITY = {
    "bilibili_human": 1,
    "bilibili_ai": 2,
    "user": 3,
    "embedded": 4,
    "asr_punct": 5,   # ASR + LLM 标点恢复（可读性优于原始 ASR）
    "asr": 6,
}


def _sha16(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


class MediaIntake:
    """把产物落成 videos + media_assets 记录。"""

    def __init__(self, video_repo: VideoRepo, asset_repo: MediaAssetRepo):
        self.videos = video_repo
        self.assets = asset_repo

    def register_video(self, meta: VideoMeta) -> dict:
        return self.videos.upsert(
            platform=meta.platform,
            platform_video_id=meta.platform_video_id or _sha16(meta.title),
            title=meta.title,
            author=meta.author,
            cover_url=meta.cover_url,
            duration_ms=meta.duration_ms,
            source_url=meta.source_url,
        )

    def attach_media(self, video_id: str, res: MediaResult, *, integrity_verdict: str,
                     acquired_from: str) -> dict:
        size = res.file_path.stat().st_size if res.file_path.exists() else 0
        asset = self.assets.add(
            video_id=video_id,
            asset_type="original_media",
            storage_path=str(res.file_path),
            sha256=res.sha256,
            size_bytes=size,
            duration_ms=res.declared_duration_ms,
            container=res.container,
            video_codec=res.vcodec,
            audio_codec=res.acodec,
            width=res.width,
            height=res.height,
            original_filename=res.file_path.name,
            status=integrity_verdict,
            acquired_from=acquired_from,
        )
        # 同步视频的媒体状态
        if integrity_verdict == "verified":
            self.videos.update_status(video_id, media_status="downloaded")
        elif integrity_verdict in ("partial", "likely"):
            self.videos.update_status(video_id, media_status="downloaded")
        else:
            self.videos.update_status(video_id, media_status="failed")
        return asset


class CaptionIntake:
    """把字幕落成 source_captions + transcript_segments。多轨并存不覆盖。"""

    def __init__(self, video_repo: VideoRepo, caption_repo: SourceCaptionRepo,
                 segment_repo: SegmentRepo):
        self.videos = video_repo
        self.captions = caption_repo
        self.segments = segment_repo

    def add_track(self, *, video_id: str, source_type: str, language: str | None,
                  cues: list[dict], is_ai_generated: bool = False,
                  completeness: str = "unknown", fmt: str = "json",
                  source_path: str | None = None,
                  media_asset_id: str | None = None) -> dict:
        cap = self.captions.add(
            video_id=video_id, source_type=source_type, language=language, cues=cues,
            media_asset_id=media_asset_id, fmt=fmt, source_path=source_path,
            is_ai_generated=is_ai_generated, completeness_status=completeness,
        )
        n = self.segments.replace_for_caption(
            video_id=video_id, source_caption_id=cap["id"],
            source_type=source_type, language=language, cues=cues)
        self.videos.update_status(
            video_id,
            transcript_status="complete" if completeness in ("complete", "verified") else (
                "partial" if completeness == "partial" else "unknown"),
        )
        cap["segment_count"] = n
        return cap

    def choose_primary(self, video_id: str) -> dict | None:
        """按来源优先级 + 完整性选主字幕轨（不删除其他轨）。"""
        tracks = self.captions.for_video(video_id)
        if not tracks:
            return None

        def key(t: dict):
            return (SOURCE_PRIORITY.get(t["source_type"], 99),
                    0 if t["completeness_status"] in ("complete", "verified") else 1)

        return sorted(tracks, key=key)[0]
