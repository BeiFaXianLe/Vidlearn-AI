"""数据访问层（Repository，S3-01）。"""
from __future__ import annotations

import hashlib
import sqlite3
import uuid
from typing import Any


def _new_id() -> str:
    return uuid.uuid4().hex


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r is not None else None


class VideoRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert(self, *, platform: str, platform_video_id: str, title: str,
               author: str | None = None, cover_url: str | None = None,
               duration_ms: int = 0, source_url: str | None = None) -> dict:
        existing = self.conn.execute(
            "SELECT * FROM videos WHERE platform=? AND platform_video_id=?",
            (platform, platform_video_id)).fetchone()
        if existing:
            self.conn.execute(
                "UPDATE videos SET title=?, author=?, cover_url=?, duration_ms=?,"
                " source_url=?, updated_at=datetime('now') WHERE id=?",
                (title, author, cover_url, duration_ms, source_url, existing["id"]))
            self.conn.commit()
            return self.get(existing["id"])
        vid = _new_id()
        self.conn.execute(
            "INSERT INTO videos(id, platform, platform_video_id, source_url, title, author,"
            " cover_url, duration_ms) VALUES(?,?,?,?,?,?,?,?)",
            (vid, platform, platform_video_id, source_url, title, author, cover_url, duration_ms))
        self.conn.commit()
        return self.get(vid)

    def get(self, video_id: str) -> dict | None:
        return _row(self.conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone())

    def update_status(self, video_id: str, *, media_status: str | None = None,
                      transcript_status: str | None = None,
                      content_scope: str | None = None) -> None:
        sets, vals = [], []
        for col, v in (("media_status", media_status),
                       ("transcript_status", transcript_status),
                       ("content_scope", content_scope)):
            if v is not None:
                sets.append(f"{col}=?"); vals.append(v)
        if not sets:
            return
        vals.append(video_id)
        self.conn.execute(
            f"UPDATE videos SET {', '.join(sets)}, updated_at=datetime('now') WHERE id=?", vals)
        self.conn.commit()

    def list(self, limit: int = 100, favorite: bool | None = None) -> list[dict]:
        if favorite is True:
            cur = self.conn.execute(
                "SELECT * FROM videos WHERE favorite=1 ORDER BY created_at DESC LIMIT ?", (limit,))
        elif favorite is False:
            cur = self.conn.execute(
                "SELECT * FROM videos WHERE favorite=0 ORDER BY created_at DESC LIMIT ?", (limit,))
        else:
            cur = self.conn.execute(
                "SELECT * FROM videos ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]

    def list_with_size(self, limit: int = 100, favorite: bool | None = None,
                       collection_id: str | None = None) -> list[dict]:
        """列表附带媒体大小与所属收藏夹（用于卡片显示）。"""
        params: list = []
        if collection_id:
            where = ("WHERE v.id IN (SELECT video_id FROM video_collections"
                     " WHERE collection_id=?)")
            params.append(collection_id)
        elif favorite is True:
            where = "WHERE v.id IN (SELECT video_id FROM video_collections)"
        elif favorite is False:
            where = "WHERE v.id NOT IN (SELECT video_id FROM video_collections)"
        else:
            where = ""
        sql = f"""SELECT v.*, COALESCE((SELECT SUM(size_bytes) FROM media_assets a
                 WHERE a.video_id=v.id AND a.asset_type='original_media'),0) AS size_bytes,
                 (SELECT GROUP_CONCAT(collection_id) FROM video_collections vc
                  WHERE vc.video_id=v.id) AS collection_ids
                FROM videos v {where} ORDER BY v.created_at DESC LIMIT ?"""
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def set_favorite(self, video_id: str, favorite: bool) -> None:
        """兼容旧接口：收藏→加入默认收藏夹；取消→移出所有收藏夹。"""
        from apps.storage.collections import CollectionRepo
        crepo = CollectionRepo(self.conn)
        if favorite:
            cid = crepo.ensure_default()
            crepo.add_membership(video_id, cid)
        else:
            crepo.clear_memberships(video_id)
        self.conn.execute("UPDATE videos SET favorite=?, updated_at=datetime('now') WHERE id=?",
                          (1 if favorite else 0, video_id))
        self.conn.commit()

    def favorite_count(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(DISTINCT video_id) c FROM video_collections").fetchone()["c"]


class SettingsRepo:
    """键值配置（如存储告警阈值）。"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get(self, key: str, default: str | None = None) -> str | None:
        r = self.conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO app_settings(key, value) VALUES(?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.conn.commit()

    def get_int(self, key: str, default: int) -> int:
        try:
            return int(self.get(key, str(default)))
        except (TypeError, ValueError):
            return default


class DocumentRepo:
    """文档资料明细（V8）。条目主体在 videos(platform='document')，此处存解析正文。"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert(self, *, video_id: str, format: str, source_path: str | None,
               size_bytes: int, sha256: str, char_count: int, content: str) -> dict:
        self.conn.execute(
            "INSERT INTO documents(video_id, format, source_path, size_bytes, sha256,"
            " char_count, content) VALUES(?,?,?,?,?,?,?)"
            " ON CONFLICT(video_id) DO UPDATE SET format=excluded.format,"
            " source_path=excluded.source_path, size_bytes=excluded.size_bytes,"
            " sha256=excluded.sha256, char_count=excluded.char_count,"
            " content=excluded.content, updated_at=datetime('now')",
            (video_id, format, source_path, size_bytes, sha256, char_count, content))
        self.conn.commit()
        return self.get(video_id)

    def get(self, video_id: str) -> dict | None:
        return _row(self.conn.execute(
            "SELECT * FROM documents WHERE video_id=?", (video_id,)).fetchone())

    def by_sha(self, sha256: str) -> dict | None:
        return _row(self.conn.execute(
            "SELECT * FROM documents WHERE sha256=?", (sha256,)).fetchone())

    def delete(self, video_id: str) -> None:
        self.conn.execute("DELETE FROM documents WHERE video_id=?", (video_id,))
        self.conn.commit()


class MediaAssetRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, *, video_id: str, asset_type: str, storage_path: str, sha256: str,
            size_bytes: int = 0, duration_ms: int = 0, container: str | None = None,
            video_codec: str | None = None, audio_codec: str | None = None,
            width: int | None = None, height: int | None = None,
            original_filename: str | None = None, mime_type: str | None = None,
            status: str = "pending", acquired_from: str | None = None,
            retention_policy: str = "keep") -> dict:
        # 去重：同 video+sha 已存在则返回
        ex = self.conn.execute(
            "SELECT * FROM media_assets WHERE video_id=? AND sha256=?",
            (video_id, sha256)).fetchone()
        if ex:
            return dict(ex)
        aid = _new_id()
        self.conn.execute(
            "INSERT INTO media_assets(id, video_id, asset_type, storage_path, original_filename,"
            " mime_type, container, video_codec, audio_codec, width, height, size_bytes,"
            " duration_ms, sha256, status, retention_policy, acquired_from)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (aid, video_id, asset_type, storage_path, original_filename, mime_type, container,
             video_codec, audio_codec, width, height, size_bytes, duration_ms, sha256, status,
             retention_policy, acquired_from))
        self.conn.commit()
        return dict(self.conn.execute("SELECT * FROM media_assets WHERE id=?", (aid,)).fetchone())

    def get(self, asset_id: str) -> dict | None:
        return _row(self.conn.execute("SELECT * FROM media_assets WHERE id=?", (asset_id,)).fetchone())

    def for_video(self, video_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM media_assets WHERE video_id=? ORDER BY created_at", (video_id,)).fetchall()]

    def set_status(self, asset_id: str, status: str) -> None:
        self.conn.execute("UPDATE media_assets SET status=? WHERE id=?", (status, asset_id))
        self.conn.commit()


class SourceCaptionRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, *, video_id: str, source_type: str, language: str | None,
            cues: list[dict], media_asset_id: str | None = None, fmt: str = "json",
            source_path: str | None = None, is_ai_generated: bool = False,
            completeness_status: str = "unknown") -> dict:
        raw = "\n".join(f"{c['start_ms']}-{c['end_ms']}:{c['text']}" for c in cues)
        h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        sid = _new_id()
        self.conn.execute(
            "INSERT INTO source_captions(id, video_id, media_asset_id, source_type, language,"
            " format, source_path, raw_text_hash, is_ai_generated, completeness_status)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (sid, video_id, media_asset_id, source_type, language, fmt, source_path, h,
             1 if is_ai_generated else 0, completeness_status))
        self.conn.commit()
        return dict(self.conn.execute(
            "SELECT * FROM source_captions WHERE id=?", (sid,)).fetchone())

    def for_video(self, video_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM source_captions WHERE video_id=? ORDER BY created_at",
            (video_id,)).fetchall()]


class SegmentRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def replace_for_caption(self, *, video_id: str, source_caption_id: str,
                            source_type: str, language: str | None,
                            cues: list[dict]) -> int:
        self.conn.execute("DELETE FROM transcript_segments WHERE source_caption_id=?",
                          (source_caption_id,))
        rows = []
        for i, c in enumerate(cues):
            rows.append((_new_id(), video_id, source_caption_id, c["start_ms"], c["end_ms"],
                         c["text"], source_type, language, c.get("confidence"), i))
        self.conn.executemany(
            "INSERT INTO transcript_segments(id, video_id, source_caption_id, start_ms, end_ms,"
            " text, source_type, language, confidence, segment_index)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
        self.conn.commit()
        return len(rows)

    def for_video(self, video_id: str, source_caption_id: str | None = None) -> list[dict]:
        if source_caption_id:
            cur = self.conn.execute(
                "SELECT * FROM transcript_segments WHERE video_id=? AND source_caption_id=?"
                " ORDER BY start_ms", (video_id, source_caption_id))
        else:
            cur = self.conn.execute(
                "SELECT * FROM transcript_segments WHERE video_id=? ORDER BY start_ms", (video_id,))
        return [dict(r) for r in cur.fetchall()]
