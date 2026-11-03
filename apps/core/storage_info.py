"""磁盘容量与占用统计（S8 增强）。

用于首页「磁盘容量」「占用空间最多的视频」卡片与阈值告警。
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from apps.storage.repositories import MediaAssetRepo, VideoRepo


def _dir_size(p: Path) -> int:
    if not p.exists():
        return 0
    total = 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def _text_bytes(conn, sql: str) -> int:
    """粗略统计文本类数据的字节数（SQLite length 对 TEXT 返回字符数，*3 近似 UTF-8）。"""
    try:
        n = conn.execute(sql).fetchone()[0] or 0
        return int(n) * 3
    except Exception:
        return 0


@dataclass
class StorageInfo:
    total_bytes: int
    used_bytes: int
    free_bytes: int
    used_pct: float
    threshold: int
    warn: bool
    danger: bool
    breakdown: dict
    top_videos: list


def get_storage(conn, data_root: Path, threshold: int = 85) -> dict:
    data_root = Path(data_root)
    try:
        usage = shutil.disk_usage(str(data_root if data_root.exists() else data_root.parent))
        total, used, free = usage.total, usage.used, usage.free
    except Exception:
        total = used = free = 0

    media = data_root / "media"
    assets = list(conn.execute(
        "SELECT asset_type, COALESCE(SUM(size_bytes),0) s FROM media_assets GROUP BY asset_type"))
    by_type = {r["asset_type"]: int(r["s"]) for r in assets}

    video_bytes = by_type.get("original_media", 0) + by_type.get("audio", 0)
    subtitle_bytes = (
        _text_bytes(conn, "SELECT COALESCE(SUM(LENGTH(text)),0) FROM transcript_segments")
        + _dir_size(media / "subtitles")
    )
    ai_bytes = (
        _text_bytes(conn, "SELECT COALESCE(SUM(LENGTH(content_json)),0) FROM summaries")
        + _text_bytes(conn, "SELECT COALESCE(SUM(LENGTH(title)+LENGTH(COALESCE(description,''))),0) FROM chapters")
        + _text_bytes(conn, "SELECT COALESCE(SUM(LENGTH(title)+LENGTH(COALESCE(content,''))),0) FROM knowledge_points")
    )
    other_bytes = _dir_size(media / "thumbnails") + _dir_size(media / "keyframes") + _dir_size(data_root / "exports")

    used_pct = round(used / total * 100, 1) if total else 0.0
    warn = used_pct >= threshold
    danger = used_pct >= 95

    # Top 5 占用最大的视频
    rows = conn.execute("""
        SELECT v.id, v.title, COALESCE(SUM(a.size_bytes),0) AS size
        FROM videos v LEFT JOIN media_assets a
          ON a.video_id = v.id AND a.asset_type='original_media'
        GROUP BY v.id ORDER BY size DESC LIMIT 5
    """).fetchall()
    top = [{"id": r["id"], "title": r["title"], "size_bytes": int(r["size"])} for r in rows
           if int(r["size"]) > 0]

    return {
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "used_pct": used_pct,
        "threshold": threshold,
        "warn": warn,
        "danger": danger,
        "breakdown": {
            "video": video_bytes,
            "subtitle": subtitle_bytes,
            "ai": ai_bytes,
            "other": other_bytes,
        },
        "top_videos": top,
    }


def is_disk_tight(conn, data_root: Path, threshold: int = 85) -> bool:
    info = get_storage(conn, data_root, threshold)
    return info["warn"]
