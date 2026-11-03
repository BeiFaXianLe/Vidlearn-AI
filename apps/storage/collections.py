"""自定义收藏夹（collections）数据访问。"""
from __future__ import annotations

import sqlite3
import uuid

DEFAULT_NAME = "默认收藏"
PALETTE = ["#536dfe", "#8b9bff", "#20a779", "#f0a34a", "#e05c5c", "#a47ec4", "#4bb6c9", "#c7a45e"]


class CollectionRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---------- 收藏夹 ----------
    def list(self) -> list[dict]:
        rows = self.conn.execute("""
            SELECT c.*, (SELECT COUNT(*) FROM video_collections vc
                         WHERE vc.collection_id=c.id) AS count
            FROM collections c ORDER BY c.sort_order, c.created_at
        """).fetchall()
        return [dict(r) for r in rows]

    def get(self, cid: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM collections WHERE id=?", (cid,)).fetchone()
        return dict(r) if r else None

    def by_name(self, name: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM collections WHERE name=?", (name,)).fetchone()
        return dict(r) if r else None

    def create(self, name: str, color: str | None = None) -> dict:
        name = (name or "").strip()
        if not name:
            raise ValueError("收藏夹名称不能为空")
        exist = self.by_name(name)
        if exist:
            return exist
        cid = uuid.uuid4().hex
        n = self.conn.execute("SELECT COUNT(*) c FROM collections").fetchone()["c"]
        color = color or PALETTE[n % len(PALETTE)]
        self.conn.execute(
            "INSERT INTO collections(id, name, color, sort_order) VALUES(?,?,?,?)",
            (cid, name, color, n))
        self.conn.commit()
        return self.get(cid)

    def rename(self, cid: str, name: str) -> dict:
        name = (name or "").strip()
        if not name:
            raise ValueError("名称不能为空")
        other = self.by_name(name)
        if other and other["id"] != cid:
            raise ValueError("已存在同名收藏夹")
        self.conn.execute("UPDATE collections SET name=? WHERE id=?", (name, cid))
        self.conn.commit()
        return self.get(cid)

    def delete(self, cid: str) -> None:
        self.conn.execute("DELETE FROM collections WHERE id=?", (cid,))
        self.conn.commit()

    def ensure_default(self) -> str:
        c = self.by_name(DEFAULT_NAME)
        if c:
            return c["id"]
        return self.create(DEFAULT_NAME)["id"]

    # ---------- 归属 ----------
    def collection_ids_for_video(self, video_id: str) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT collection_id FROM video_collections WHERE video_id=?", (video_id,))]

    def add_membership(self, video_id: str, collection_id: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO video_collections(video_id, collection_id) VALUES(?,?)",
            (video_id, collection_id))
        self.conn.commit()

    def remove_membership(self, video_id: str, collection_id: str) -> None:
        self.conn.execute(
            "DELETE FROM video_collections WHERE video_id=? AND collection_id=?",
            (video_id, collection_id))
        self.conn.commit()

    def set_memberships(self, video_id: str, collection_ids: list[str]) -> list[str]:
        """整体设置某视频所属的收藏夹（覆盖）。"""
        self.conn.execute("DELETE FROM video_collections WHERE video_id=?", (video_id,))
        for cid in dict.fromkeys(collection_ids):
            self.conn.execute(
                "INSERT OR IGNORE INTO video_collections(video_id, collection_id) VALUES(?,?)",
                (video_id, cid))
        self.conn.commit()
        # 同步 favorite 标志（有任意收藏夹即 1）
        self.conn.execute("UPDATE videos SET favorite=? WHERE id=?",
                          (1 if collection_ids else 0, video_id))
        self.conn.commit()
        return self.collection_ids_for_video(video_id)

    def toggle(self, video_id: str, collection_id: str) -> bool:
        cur = self.collection_ids_for_video(video_id)
        if collection_id in cur:
            self.remove_membership(video_id, collection_id)
        else:
            self.add_membership(video_id, collection_id)
        ids = self.collection_ids_for_video(video_id)
        self.conn.execute("UPDATE videos SET favorite=? WHERE id=?",
                          (1 if ids else 0, video_id))
        self.conn.commit()
        return collection_id in ids

    def clear_memberships(self, video_id: str) -> None:
        self.conn.execute("DELETE FROM video_collections WHERE video_id=?", (video_id,))
        self.conn.execute("UPDATE videos SET favorite=0 WHERE id=?", (video_id,))
        self.conn.commit()
