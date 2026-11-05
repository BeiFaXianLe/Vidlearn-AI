"""S7 视频库与业务闭环：学习进度、笔记、Markdown 导出、删除。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from apps.storage import DocumentRepo, MediaAssetRepo, SegmentRepo, SourceCaptionRepo, VideoRepo
from apps.storage.analysis_repos import ChapterRepo, KnowledgePointRepo, SummaryRepo

router = APIRouter(prefix="/api", tags=["s7"])


class ProgressIn(BaseModel):
    position_ms: int
    duration_ms: int = 0


class NoteIn(BaseModel):
    content: str
    chapter_id: str | None = None
    start_ms: int | None = None


def _db(request: Request):
    return request.app.state.db


@router.put("/videos/{video_id}/progress")
def save_progress(video_id: str, body: ProgressIn, request: Request):
    db = _db(request)
    with request.app.state.db_lock:
        if not VideoRepo(db).get(video_id):
            raise HTTPException(status_code=404, detail="视频不存在")
        done = 1 if body.duration_ms and body.position_ms >= body.duration_ms - 3000 else 0
        db.execute(
            "INSERT INTO learning_progress(video_id, position_ms, duration_ms, completed, last_watched_at)"
            " VALUES(?,?,?,?,datetime('now'))"
            " ON CONFLICT(video_id) DO UPDATE SET position_ms=excluded.position_ms,"
            " duration_ms=excluded.duration_ms, completed=excluded.completed,"
            " last_watched_at=datetime('now')",
            (video_id, body.position_ms, body.duration_ms, done))
        db.commit()
    return {"ok": True}


@router.get("/videos/{video_id}/progress")
def get_progress(video_id: str, request: Request):
    db = _db(request)
    r = db.execute("SELECT * FROM learning_progress WHERE video_id=?", (video_id,)).fetchone()
    return {"ok": True, "progress": dict(r) if r else None}


@router.get("/videos/{video_id}/notes")
def get_notes(video_id: str, request: Request):
    db = _db(request)
    rows = [dict(r) for r in db.execute(
        "SELECT * FROM notes WHERE video_id=? ORDER BY updated_at DESC", (video_id,)).fetchall()]
    return {"ok": True, "notes": rows}


@router.post("/videos/{video_id}/notes")
def add_note(video_id: str, body: NoteIn, request: Request):
    import uuid
    db = _db(request)
    with request.app.state.db_lock:
        if not VideoRepo(db).get(video_id):
            raise HTTPException(status_code=404, detail="视频不存在")
        nid = uuid.uuid4().hex
        db.execute("INSERT INTO notes(id, video_id, chapter_id, start_ms, content) VALUES(?,?,?,?,?)",
                   (nid, video_id, body.chapter_id, body.start_ms, body.content))
        db.commit()
    return {"ok": True, "id": nid}


@router.delete("/videos/{video_id}")
def delete_video(video_id: str, request: Request, delete_media: bool = True,
                 delete_knowledge: bool = True):
    """删除视频。delete_media=删除媒体文件；delete_knowledge=删除字幕/总结/笔记等索引。"""
    st = request.app.state
    db = st.db
    import os
    with st.db_lock:
        v = VideoRepo(db).get(video_id)
        if not v:
            raise HTTPException(status_code=404, detail="视频不存在")
        assets = MediaAssetRepo(db).for_video(video_id)
        # 文档资料：解析正文随条目级联删除；源文件需显式清理
        doc = DocumentRepo(db).get(video_id)
        if delete_media:
            for a in assets:
                p = a["storage_path"]
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except OSError:
                    pass
            if doc and doc.get("source_path"):
                try:
                    if os.path.exists(doc["source_path"]):
                        os.remove(doc["source_path"])
                except OSError:
                    pass
        if delete_knowledge:
            db.execute("DELETE FROM videos WHERE id=?", (video_id,))  # 级联删其余
        else:
            # 仅删媒体资产记录，保留知识资产，视频条目标记为无媒体
            db.execute("DELETE FROM media_assets WHERE video_id=?", (video_id,))
            VideoRepo(db).update_status(video_id, media_status="unavailable")
        db.commit()
    return {"ok": True, "deleted_media": delete_media, "deleted_knowledge": delete_knowledge}


@router.get("/videos/{video_id}/export.md")
def export_markdown(video_id: str, request: Request):
    from fastapi.responses import PlainTextResponse
    db = _db(request)
    v = VideoRepo(db).get(video_id)
    if not v:
        raise HTTPException(status_code=404, detail="视频不存在")
    s = SummaryRepo(db).latest(video_id)
    chapters = ChapterRepo(db).for_video(video_id)
    points = KnowledgePointRepo(db).for_video(video_id)
    notes = [dict(r) for r in db.execute(
        "SELECT * FROM notes WHERE video_id=? ORDER BY updated_at DESC", (video_id,)).fetchall()]

    def t(ms):
        if ms is None:
            return "--:--"
        s2 = ms // 1000
        return f"{s2//3600:d}:{(s2%3600)//60:02d}:{s2%60:02d}" if s2 >= 3600 else f"{(s2%3600)//60:02d}:{s2%60:02d}"

    lines = [f"# {v['title']}", ""]
    lines.append(f"- 平台：{v['platform']}")
    if v.get("author"):
        lines.append(f"- 作者：{v['author']}")
    if v.get("source_url"):
        lines.append(f"- 来源：{v['source_url']}")
    lines.append(f"- 时长：{t(v.get('duration_ms'))}")
    lines.append(f"- 内容范围：{v.get('content_scope')}")
    lines.append("")
    if s:
        c = s.get("content") or {}
        lines.append("## AI 总结")
        if c.get("one_liner"):
            lines += [f"> {c['one_liner']}", ""]
        if c.get("key_points"):
            lines.append("### 核心要点")
            lines += [f"- {p}" for p in c["key_points"]]
            lines.append("")
        if c.get("terms"):
            lines.append("### 关键术语")
            lines.append("、".join(c["terms"]))
            lines.append("")
    if chapters:
        lines.append("## 章节")
        for ch in chapters:
            lines.append(f"- `{t(ch['start_ms'])}` {ch['title']}" +
                         (f" —— {ch['description']}" if ch.get("description") else ""))
        lines.append("")
    if points:
        lines.append("## 知识点")
        for p in points:
            lines.append(f"- **{p['title']}**" + (f"（{t(p['start_ms'])}）" if p.get("start_ms") is not None else ""))
            if p.get("content"):
                lines.append(f"  {p['content']}")
        lines.append("")
    if notes:
        lines.append("## 我的笔记")
        for n in notes:
            lines.append(f"- {n['content']}")
        lines.append("")
    # 字幕全文（合并成段，便于阅读）
    segs = [dict(r) for r in db.execute(
        "SELECT id, start_ms, end_ms, text FROM transcript_segments WHERE video_id=?"
        " ORDER BY start_ms", (video_id,)).fetchall()]
    if segs:
        from apps.core.textnorm import merge_cues
        paras = merge_cues(segs)
        lines.append("## 字幕全文")
        lines.append("")
        for p in paras:
            lines.append(f"`{t(p['start_ms'])}` {p['text']}")
            lines.append("")
    md = "\n".join(lines)
    return PlainTextResponse(md, media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="{video_id}.md"'})


@router.get("/stats")
def stats(request: Request):
    db = _db(request)
    vids = db.execute("SELECT COUNT(*) c FROM videos").fetchone()["c"]
    dur = db.execute("SELECT COALESCE(SUM(duration_ms),0) s FROM videos").fetchone()["s"]
    sums = db.execute("SELECT COUNT(*) c FROM summaries").fetchone()["c"]
    done = db.execute("SELECT COUNT(*) c FROM learning_progress WHERE completed=1").fetchone()["c"]
    return {"ok": True, "videos": vids, "duration_ms": dur, "summaries": sums, "completed": done}
