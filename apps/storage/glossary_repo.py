"""术语表（glossary）数据访问 + 术语抽取。"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid

CATEGORIES = ["品牌", "产品", "人名", "组织", "术语", "其他"]

# 抽取候选术语时排除的常见虚词/口水词
_STOP = set("""我们 你们 他们 大家 今天 这个 那个 然后 就是 所以 因为 但是 如果
可以 应该 需要 一个 一些 这里 那里 现在 时候 什么 怎么 这样 那样 其实 已经
感谢 各位 朋友 嘉宾 上午 下午 晚上 你好 大家好""".split())


class GlossaryRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def list(self, video_id: str | None = None, include_disabled: bool = False) -> list[dict]:
        sql = "SELECT * FROM glossary WHERE 1=1"
        params: list = []
        if video_id:
            sql += " AND (scope='global' OR video_id=?)"
            params.append(video_id)
        if not include_disabled:
            sql += " AND enabled=1"
        sql += " ORDER BY weight DESC, created_at"
        return [dict(r) for r in self.conn.execute(sql, params)]

    def get(self, gid: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM glossary WHERE id=?", (gid,)).fetchone()
        return dict(r) if r else None

    def add(self, term: str, *, variants: list[str] | None = None, category: str | None = None,
            scope: str = "global", video_id: str | None = None, weight: int = 0,
            enabled: bool = True) -> dict:
        term = (term or "").strip()
        if not term:
            raise ValueError("术语不能为空")
        if scope not in ("global", "video"):
            raise ValueError("scope 必须是 global 或 video")
        if scope == "video" and not video_id:
            raise ValueError("video 级术语需提供 video_id")
        exist = self.conn.execute(
            "SELECT * FROM glossary WHERE scope=? AND COALESCE(video_id,'')=? AND term=?",
            (scope, video_id or "", term)).fetchone()
        if exist:
            # 合并 variants
            cur = set(json.loads(exist["variants"] or "[]"))
            cur |= set(v for v in (variants or []) if v and v != term)
            self.conn.execute("UPDATE glossary SET variants=?, category=COALESCE(?,category),"
                              " weight=MAX(weight,?) WHERE id=?",
                              (json.dumps(sorted(cur), ensure_ascii=False), category, weight, exist["id"]))
            self.conn.commit()
            return self.get(exist["id"])
        gid = uuid.uuid4().hex
        self.conn.execute(
            "INSERT INTO glossary(id,scope,video_id,term,variants,category,weight,enabled)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (gid, scope, video_id if scope == "video" else None, term,
             json.dumps([v for v in (variants or []) if v and v != term], ensure_ascii=False),
             category, weight, 1 if enabled else 0))
        self.conn.commit()
        return self.get(gid)

    def update(self, gid: str, **fields) -> dict | None:
        allowed = {"term", "variants", "category", "weight", "enabled"}
        sets, params = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k == "variants" and isinstance(v, list):
                v = json.dumps(v, ensure_ascii=False)
            if k == "enabled":
                v = 1 if v else 0
            sets.append(f"{k}=?")
            params.append(v)
        if sets:
            params.append(gid)
            self.conn.execute(f"UPDATE glossary SET {', '.join(sets)} WHERE id=?", params)
            self.conn.commit()
        return self.get(gid)

    def delete(self, gid: str) -> None:
        self.conn.execute("DELETE FROM glossary WHERE id=?", (gid,))
        self.conn.commit()

    def resolved_terms(self, video_id: str | None) -> list[dict]:
        """合并 global + 该视频专用术语（按 term 去重，video 级优先）。"""
        rows = self.list(video_id=video_id)
        seen: dict[str, dict] = {}
        for r in rows:
            key = r["term"]
            if key not in seen or (r["scope"] == "video" and seen[key]["scope"] == "global"):
                seen[key] = r
        return list(seen.values())


def extract_candidates(texts: list[str], limit: int = 40) -> list[str]:
    """从标题/简介/总结用语中抽取候选术语（启发式，供用户确认后入库）。

    - 中文 2-12 字连续片段，去掉虚词/口水词
    - 含英文字母的产品名/缩写（如 StarRocks、AI、RAG）
    - 按出现频次排序
    """
    freq: dict[str, int] = {}
    for t in texts:
        if not t:
            continue
        # 英文/数字标识符（2 字符以上，含大小写混合或全大写）
        for w in re.findall(r"[A-Za-z][A-Za-z0-9+#.]{1,20}", t):
            if len(w) >= 2 and (w.isupper() or any(c.isupper() for c in w[1:])):
                freq[w] = freq.get(w, 0) + 2
        # 中文片段：整体 + 常见品牌后缀截取
        for seg in re.findall(r"[\u4e00-\u9fff]{2,20}", t):
            if seg in _STOP:
                continue
            freq[seg] = freq.get(seg, 0) + 1
            # 抽取「XX科技/公司/集团/系统/平台/数据库」这类主体词
            for m in re.finditer(r"([\u4e00-\u9fff]{2,8}?(?:科技|公司|集团|系统|平台|数据库|框架|模型|引擎))", seg):
                w = m.group(1)
                if w not in _STOP:
                    freq[w] = freq.get(w, 0) + 2
    items = [k for k, _ in sorted(freq.items(), key=lambda kv: -kv[1])]
    return items[:limit]
