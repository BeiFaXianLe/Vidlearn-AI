"""字幕校准 API（S9）：术语表、质量评分、校准任务、变更复核、首选轨/回退。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from apps.core.logging_setup import get_logger
from apps.storage import (
    CaptionChangeRepo,
    CaptionQCRepo,
    GlossaryRepo,
    MediaAssetRepo,
    SegmentRepo,
    SettingsRepo,
    SourceCaptionRepo,
    VideoRepo,
    extract_candidates,
)

router = APIRouter(prefix="/api", tags=["calibrate"])
log = get_logger("calibrate")


def _db(request: Request):
    return request.app.state.db


def _repos(conn):
    return (VideoRepo(conn), SourceCaptionRepo(conn), SegmentRepo(conn))


# ---------------- 术语表 CRUD ----------------
class GlossaryIn(BaseModel):
    term: str
    variants: list[str] | None = None
    category: str | None = None
    scope: str = "global"
    video_id: str | None = None
    weight: int = 0


class GlossaryPatch(BaseModel):
    term: str | None = None
    variants: list[str] | None = None
    category: str | None = None
    weight: int | None = None
    enabled: bool | None = None


@router.get("/glossary")
def list_glossary(request: Request, video_id: str | None = None):
    with request.app.state.db_lock:
        return {"ok": True, "terms": GlossaryRepo(_db(request)).list(video_id)}


@router.post("/glossary")
def add_glossary(body: GlossaryIn, request: Request):
    with request.app.state.db_lock:
        try:
            g = GlossaryRepo(_db(request)).add(
                body.term, variants=body.variants, category=body.category,
                scope=body.scope, video_id=body.video_id, weight=body.weight)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "term": g}


@router.patch("/glossary/{gid}")
def patch_glossary(gid: str, body: GlossaryPatch, request: Request):
    with request.app.state.db_lock:
        repo = GlossaryRepo(_db(request))
        if not repo.get(gid):
            raise HTTPException(status_code=404, detail="术语不存在")
        g = repo.update(gid, **body.model_dump(exclude_none=True))
    return {"ok": True, "term": g}


@router.delete("/glossary/{gid}")
def delete_glossary(gid: str, request: Request):
    with request.app.state.db_lock:
        repo = GlossaryRepo(_db(request))
        if not repo.get(gid):
            raise HTTPException(status_code=404, detail="术语不存在")
        repo.delete(gid)
    return {"ok": True}


class ExtractIn(BaseModel):
    video_id: str
    save: bool = False
    scope: str = "video"


@router.post("/glossary/extract")
def extract_glossary(body: ExtractIn, request: Request):
    """从视频标题/作者 + AI 总结的术语里抽取候选（可选直接保存为该视频术语）。"""
    st = request.app.state
    with st.db_lock:
        video = VideoRepo(st.db).get(body.video_id)
        if not video:
            raise HTTPException(status_code=404, detail="视频不存在")
        texts = [video.get("title") or "", video.get("author") or ""]
        row = st.db.execute(
            "SELECT content_json FROM summaries WHERE video_id=? ORDER BY created_at DESC LIMIT 1",
            (body.video_id,)).fetchone()
        if row:
            try:
                data = json.loads(row["content_json"])
                texts += data.get("terms", []) or []
                texts += data.get("key_points", []) or []
                texts.append(data.get("one_liner") or "")
            except Exception:
                pass
        candidates = extract_candidates(texts)
        saved = []
        if body.save and candidates:
            repo = GlossaryRepo(st.db)
            for term in candidates:
                try:
                    saved.append(repo.add(term, scope=body.scope,
                                          video_id=body.video_id if body.scope == "video" else None,
                                          category="术语").get("term"))
                except ValueError:
                    pass
    return {"ok": True, "candidates": candidates, "saved": saved}


# ---------------- 质量评分 ----------------
@router.get("/videos/{video_id}/subtitle-qc")
def subtitle_qc(video_id: str, request: Request, caption_id: str | None = None):
    st = request.app.state
    with st.db_lock:
        from apps.core.intake import CaptionIntake
        vrepo, crepo, srepo = _repos(st.db)
        video = vrepo.get(video_id)
        if not video:
            raise HTTPException(status_code=404, detail="视频不存在")
        cap = None
        if caption_id:
            cap = next((t for t in crepo.for_video(video_id) if t["id"] == caption_id), None)
        else:
            cap = CaptionIntake(vrepo, crepo, srepo).choose_primary(video_id)
        if not cap:
            return {"ok": True, "caption_id": None, "score": None, "issues": [],
                    "stats": {}, "message": "该视频还没有字幕"}
        cues = srepo.for_video(video_id, cap["id"])
        variants = []
        for t in GlossaryRepo(st.db).resolved_terms(video_id):
            vs = t.get("variants")
            if isinstance(vs, str):
                try:
                    vs = json.loads(vs)
                except Exception:
                    vs = [x for x in vs.split(",") if x]
            variants += [v for v in (vs or []) if isinstance(v, str) and len(v) >= 2]
        from apps.core.subtitle_qc import score_cues
        rep = score_cues(cues, duration_ms=video.get("duration_ms"), glossary_variants=variants)
        cached = CaptionQCRepo(st.db).get(cap["id"])
    return {"ok": True, "caption_id": cap["id"], "source_type": cap["source_type"],
            "score": rep["score"], "issues": rep["issues"][:200],
            "stats": rep["stats"], "cached": cached}


# ---------------- 校准任务 ----------------
class CalibrateIn(BaseModel):
    caption_id: str | None = None
    do_llm: bool = True
    do_align: bool = True


@router.post("/videos/{video_id}/calibrate")
async def calibrate_video(video_id: str, body: CalibrateIn, request: Request):
    st = request.app.state
    with st.db_lock:
        if not VideoRepo(st.db).get(video_id):
            raise HTTPException(status_code=404, detail="视频不存在")
        n_tracks = len(SourceCaptionRepo(st.db).for_video(video_id))
    if n_tracks == 0:
        raise HTTPException(status_code=400, detail="该视频还没有字幕，无法校准")
    payload = {"video_id": video_id, "caption_id": body.caption_id,
               "do_llm": body.do_llm, "do_align": body.do_align}
    job_id = st.jobs.create(stage="准备校准", payload=payload)
    asyncio.create_task(_run_calibrate(request.app, job_id, payload))
    return {"ok": True, "task_id": job_id, "async": True}


async def _run_calibrate(app, job_id: str, payload: dict) -> None:
    st = app.state
    db = st.db
    video_id = payload["video_id"]
    try:
        from apps.core.calibrate import calibrate
        from apps.core.intake import CaptionIntake, SOURCE_PRIORITY

        with st.db_lock:
            vrepo, crepo, srepo = _repos(db)
            vmd = vrepo.get(video_id)
            cap = None
            if payload.get("caption_id"):
                cap = next((t for t in crepo.for_video(video_id) if t["id"] == payload["caption_id"]), None)
            if not cap:
                cap = CaptionIntake(vrepo, crepo, srepo).choose_primary(video_id)
            if not cap:
                st.jobs.update(job_id, status="error", stage="失败", error={"message": "无字幕轨"})
                return
            cues = srepo.for_video(video_id, cap["id"])
            terms = GlossaryRepo(db).resolved_terms(video_id)
            media_path = None
            for a in MediaAssetRepo(db).for_video(video_id):
                if a.get("asset_type") == "original_media" and Path(a["storage_path"]).exists():
                    media_path = Path(a["storage_path"])
                    break

        llm = None
        if payload.get("do_llm") and st.settings.llm_api_key:
            from apps.core.ai import LLMConfig, OpenAICompatibleLLM
            llm = getattr(st, "llm", None) or OpenAICompatibleLLM(LLMConfig(
                base_url=st.settings.llm_base_url, api_key=st.settings.llm_api_key,
                model=st.settings.llm_model))
            st.llm = llm

        def progress(stage, pct):
            st.jobs.update(job_id, stage=stage, progress=min(95, int(pct)))

        st.jobs.update(job_id, stage="校准中", progress=5)
        res = await calibrate(
            cues, terms=terms, llm=llm,
            media_path=media_path, ffmpeg=st.settings.ffmpeg_path,
            duration_ms=vmd.get("duration_ms") if vmd else None,
            do_pinyin=True, do_llm=bool(llm), do_align=payload.get("do_align", True),
            progress=progress)

        with st.db_lock:
            new_cap = CaptionIntake(vrepo, crepo, srepo).add_track(
                video_id=video_id, source_type="asr_corrected", language=cap.get("language") or "zh",
                cues=res.cues, is_ai_generated=True,
                completeness=cap.get("completeness_status") or "complete", fmt="json")
            n_changes = CaptionChangeRepo(db).add_many(video_id, new_cap["id"], res.changes)
            CaptionQCRepo(db).save(video_id, cap["id"], res.qc_before.get("score", 0), res.qc_before)
            CaptionQCRepo(db).save(video_id, new_cap["id"], res.qc_after.get("score", 0), res.qc_after)
            # 设为该视频首选字幕
            SettingsRepo(db).set(f"preferred_caption:{video_id}", new_cap["id"])
            vrepo.update_status(video_id, transcript_status="complete")

        st.jobs.update(job_id, status="done", stage="完成", progress=100, result={
            "caption_id": new_cap["id"], "changes": n_changes,
            "qc_before": res.qc_before.get("score"), "qc_after": res.qc_after.get("score"),
            "llm_used": res.llm_used, "align_used": res.align_used,
            "dropped_llm": res.dropped_llm,
        })
    except Exception as e:  # noqa: BLE001
        log.warning("校准失败: %s", str(e)[:200])
        st.jobs.update(job_id, status="error", stage="失败", error={"message": str(e)[:300]})


# ---------------- 手动名词替换（全局替换到本视频字幕） ----------------
class ReplaceIn(BaseModel):
    old: str
    new: str
    caption_id: str | None = None


@router.post("/videos/{video_id}/subtitle-replace")
def subtitle_replace(video_id: str, body: ReplaceIn, request: Request):
    """把当前主字幕里出现的「old」全部替换为「new」（手动纠错），记录变更日志。"""
    old = (body.old or "").strip()
    new = (body.new or "").strip()
    if not old:
        raise HTTPException(status_code=400, detail="旧写法不能为空")
    st = request.app.state
    with st.db_lock:
        from apps.core.intake import CaptionIntake
        vrepo, crepo, srepo = _repos(st.db)
        if not vrepo.get(video_id):
            raise HTTPException(status_code=404, detail="视频不存在")
        cap = None
        if body.caption_id:
            cap = next((t for t in crepo.for_video(video_id) if t["id"] == body.caption_id), None)
        if not cap:
            cap = CaptionIntake(vrepo, crepo, srepo).choose_primary(video_id)
        if not cap:
            raise HTTPException(status_code=400, detail="该视频还没有字幕")
        segs = srepo.for_video(video_id, cap["id"])
        changes = []
        n = 0
        for s in segs:
            txt = s.get("text") or ""
            if old in txt:
                nt = txt.replace(old, new)
                st.db.execute("UPDATE transcript_segments SET text=? WHERE id=?", (nt, s["id"]))
                changes.append({"segment_index": s.get("segment_index"), "start_ms": s.get("start_ms"),
                                "before": txt, "after": nt, "reason": "manual", "confidence": 1.0})
                n += 1
        st.db.commit()
        if changes:
            CaptionChangeRepo(st.db).add_many(video_id, cap["id"], changes)
    return {"ok": True, "replaced": n, "segments": len(segs), "caption_id": cap["id"]}


# ---------------- 变更复核 / 首选轨 / 回退 ----------------
@router.get("/videos/{video_id}/caption-changes")
def caption_changes(video_id: str, request: Request, caption_id: str | None = None):
    st = request.app.state
    with st.db_lock:
        crepo = SourceCaptionRepo(st.db)
        cid = caption_id
        if not cid:
            row = st.db.execute(
                "SELECT value FROM app_settings WHERE key=?",
                (f"preferred_caption:{video_id}",)).fetchone()
            cid = row[0] if row else None
        if not cid:
            tracks = [t for t in crepo.for_video(video_id) if t["source_type"] == "asr_corrected"]
            cid = tracks[-1]["id"] if tracks else None
        if not cid:
            return {"ok": True, "caption_id": None, "changes": []}
        return {"ok": True, "caption_id": cid,
                "changes": CaptionChangeRepo(st.db).list(cid)}


class PreferredIn(BaseModel):
    caption_id: str


@router.post("/videos/{video_id}/preferred-caption")
def set_preferred(video_id: str, body: PreferredIn, request: Request):
    st = request.app.state
    with st.db_lock:
        if not VideoRepo(st.db).get(video_id):
            raise HTTPException(status_code=404, detail="视频不存在")
        tracks = {t["id"]: t for t in SourceCaptionRepo(st.db).for_video(video_id)}
        if body.caption_id not in tracks:
            raise HTTPException(status_code=404, detail="字幕轨不存在")
        SettingsRepo(st.db).set(f"preferred_caption:{video_id}", body.caption_id)
    return {"ok": True, "caption_id": body.caption_id}


@router.delete("/videos/{video_id}/captions/{caption_id}")
def delete_caption(video_id: str, caption_id: str, request: Request):
    """删除某字幕轨（撤销校准/回退）。会级联删除其分段、变更与评分。"""
    st = request.app.state
    with st.db_lock:
        tracks = {t["id"]: t for t in SourceCaptionRepo(st.db).for_video(video_id)}
        if caption_id not in tracks:
            raise HTTPException(status_code=404, detail="字幕轨不存在")
        st.db.execute("DELETE FROM source_captions WHERE id=?", (caption_id,))
        row = st.db.execute("SELECT value FROM app_settings WHERE key=?",
                            (f"preferred_caption:{video_id}",)).fetchone()
        if row and row[0] == caption_id:
            st.db.execute("DELETE FROM app_settings WHERE key=?", (f"preferred_caption:{video_id}",))
        st.db.commit()
    return {"ok": True}
