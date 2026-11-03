"""字幕校准：变更日志 + 质量报告 数据访问。"""
from __future__ import annotations

import json
import sqlite3
import uuid


class CaptionChangeRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add_many(self, video_id: str, caption_id: str, changes: list[dict]) -> int:
        rows = []
        for ch in changes:
            tf = ch.get("time_from"); tt = ch.get("time_to")
            rows.append((uuid.uuid4().hex, video_id, caption_id,
                         ch.get("segment_index"), ch.get("start_ms"),
                         ch.get("before", ""), ch.get("after", ""),
                         ch.get("reason", "unknown"), ch.get("confidence"),
                         tf[0] if tf else None, tt[1] if tt else None))
        if not rows:
            return 0
        self.conn.executemany(
            "INSERT INTO caption_changes(id,video_id,caption_id,segment_index,start_ms,"
            "before,after,reason,confidence,time_from_ms,time_to_ms) VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
        self.conn.commit()
        return len(rows)

    def list(self, caption_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM caption_changes WHERE caption_id=? ORDER BY segment_index, start_ms",
            (caption_id,))]

    def count(self, caption_id: str) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) c FROM caption_changes WHERE caption_id=?", (caption_id,)).fetchone()["c"]

    def delete_for(self, caption_id: str) -> None:
        self.conn.execute("DELETE FROM caption_changes WHERE caption_id=?", (caption_id,))
        self.conn.commit()


class CaptionQCRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def save(self, video_id: str, caption_id: str, score: float, report: dict) -> None:
        self.conn.execute(
            "INSERT INTO caption_qc(caption_id,video_id,score,report_json) VALUES(?,?,?,?)"
            " ON CONFLICT(caption_id) DO UPDATE SET score=excluded.score, report_json=excluded.report_json",
            (caption_id, video_id, float(score), json.dumps(report, ensure_ascii=False)))
        self.conn.commit()

    def get(self, caption_id: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM caption_qc WHERE caption_id=?", (caption_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        try:
            d["report"] = json.loads(d.pop("report_json"))
        except Exception:
            d["report"] = {}
        return d
