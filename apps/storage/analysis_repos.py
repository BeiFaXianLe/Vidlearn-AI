"""S5 分析结果持久化 Repository（summaries / chapters / knowledge_points）。"""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any


def _id() -> str:
    return uuid.uuid4().hex


class SummaryRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, *, video_id: str, mode: str, content: dict, content_scope: str = "unknown",
            model: str | None = None, provider: str | None = None,
            prompt_version: str | None = None, transcript_hash: str | None = None,
            plain_text: str | None = None) -> dict:
        sid = _id()
        self.conn.execute(
            "INSERT INTO summaries(id, video_id, mode, content_json, plain_text, content_scope,"
            " model, provider, prompt_version, transcript_hash) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (sid, video_id, mode, json.dumps(content, ensure_ascii=False), plain_text,
             content_scope, model, provider, prompt_version, transcript_hash))
        self.conn.commit()
        return self.get(sid)

    def get(self, sid: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM summaries WHERE id=?", (sid,)).fetchone()
        return _parse_summary(dict(r)) if r else None

    def latest(self, video_id: str, mode: str | None = None) -> dict | None:
        if mode:
            r = self.conn.execute(
                "SELECT * FROM summaries WHERE video_id=? AND mode=? ORDER BY created_at DESC LIMIT 1",
                (video_id, mode)).fetchone()
        else:
            r = self.conn.execute(
                "SELECT * FROM summaries WHERE video_id=? ORDER BY created_at DESC LIMIT 1",
                (video_id,)).fetchone()
        return _parse_summary(dict(r)) if r else None

    def for_video(self, video_id: str) -> list[dict]:
        return [_parse_summary(dict(r)) for r in self.conn.execute(
            "SELECT * FROM summaries WHERE video_id=? ORDER BY created_at DESC", (video_id,)).fetchall()]


def _parse_summary(d: dict) -> dict:
    try:
        d["content"] = json.loads(d.get("content_json") or "{}")
    except json.JSONDecodeError:
        d["content"] = {}
    return d


class ChapterRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def replace_for_video(self, video_id: str, chapters: list[dict]) -> int:
        self.conn.execute("DELETE FROM chapters WHERE video_id=?", (video_id,))
        rows = []
        for i, c in enumerate(chapters):
            rows.append((_id(), video_id, c.get("title", ""), c.get("start_ms"),
                         c.get("end_ms"), c.get("summary") or c.get("description"),
                         c.get("timestamp_source", "subtitle"), c.get("confidence"), i))
        self.conn.executemany(
            "INSERT INTO chapters(id, video_id, title, start_ms, end_ms, description,"
            " timestamp_source, confidence, sort_order) VALUES(?,?,?,?,?,?,?,?,?)", rows)
        self.conn.commit()
        return len(rows)

    def for_video(self, video_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM chapters WHERE video_id=? ORDER BY sort_order", (video_id,)).fetchall()]


class KnowledgePointRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def replace_for_video(self, video_id: str, points: list[dict]) -> int:
        self.conn.execute("DELETE FROM knowledge_points WHERE video_id=?", (video_id,))
        rows = []
        for p in points:
            rows.append((_id(), video_id, p.get("title", ""), p.get("content"),
                         p.get("start_ms"), p.get("end_ms"),
                         json.dumps(p.get("source_refs") or [], ensure_ascii=False),
                         json.dumps(p.get("tags") or [], ensure_ascii=False)))
        self.conn.executemany(
            "INSERT INTO knowledge_points(id, video_id, title, content, start_ms, end_ms,"
            " source_refs_json, tags_json) VALUES(?,?,?,?,?,?,?,?)", rows)
        self.conn.commit()
        return len(rows)

    def for_video(self, video_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM knowledge_points WHERE video_id=?", (video_id,)).fetchall()]
