"""V2 增强 API：磁盘容量、收藏夹、批量导入、任务控制、视频问答（SSE）。"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from apps.core.intake import CaptionIntake
from apps.core.logging_setup import get_logger
from apps.core.qa import SYSTEM as QA_SYSTEM, build_qa_context, build_user_prompt, extract_citations
from apps.core.storage_info import get_storage
from apps.storage import (
    SegmentRepo,
    SettingsRepo,
    SourceCaptionRepo,
    VideoRepo,
)

router = APIRouter(prefix="/api", tags=["v2-ext"])
log = get_logger("ext")

THRESHOLD_KEY = "storage_warn_threshold"


def _db(request: Request):
    return request.app.state.db


def _threshold(request: Request) -> int:
    return SettingsRepo(_db(request)).get_int(THRESHOLD_KEY, 85)


# ---------------- 磁盘容量 ----------------
@router.get("/storage")
def storage(request: Request):
    st = request.app.state
    with st.db_lock:
        info = get_storage(_db(request), st.settings.data_root, _threshold(request))
    return {"ok": True, **info}


class ThresholdIn(BaseModel):
    threshold: int


@router.put("/storage/threshold")
def set_threshold(body: ThresholdIn, request: Request):
    t = max(50, min(99, int(body.threshold)))
    with request.app.state.db_lock:
        SettingsRepo(_db(request)).set(THRESHOLD_KEY, str(t))
    return {"ok": True, "threshold": t}


# ---------------- 收藏夹（自定义） ----------------
class CollectionIn(BaseModel):
    name: str
    color: str | None = None


class MembershipIn(BaseModel):
    collection_ids: list[str] = []


@router.get("/collections")
def list_collections(request: Request):
    with request.app.state.db_lock:
        from apps.storage import CollectionRepo
        return {"ok": True, "collections": CollectionRepo(_db(request)).list()}


@router.post("/collections")
def create_collection(body: CollectionIn, request: Request):
    with request.app.state.db_lock:
        from apps.storage import CollectionRepo
        try:
            c = CollectionRepo(_db(request)).create(body.name, body.color)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "collection": c}


@router.patch("/collections/{cid}")
def rename_collection(cid: str, body: CollectionIn, request: Request):
    with request.app.state.db_lock:
        from apps.storage import CollectionRepo
        repo = CollectionRepo(_db(request))
        if not repo.get(cid):
            raise HTTPException(status_code=404, detail="收藏夹不存在")
        try:
            c = repo.rename(cid, body.name)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "collection": c}


@router.delete("/collections/{cid}")
def delete_collection(cid: str, request: Request):
    with request.app.state.db_lock:
        from apps.storage import CollectionRepo
        repo = CollectionRepo(_db(request))
        if not repo.get(cid):
            raise HTTPException(status_code=404, detail="收藏夹不存在")
        repo.delete(cid)
    return {"ok": True}


@router.get("/videos/{video_id}/collections")
def video_collections(video_id: str, request: Request):
    with request.app.state.db_lock:
        from apps.storage import CollectionRepo
        return {"ok": True, "collection_ids": CollectionRepo(_db(request)).collection_ids_for_video(video_id)}


@router.put("/videos/{video_id}/collections")
def set_video_collections(video_id: str, body: MembershipIn, request: Request):
    with request.app.state.db_lock:
        from apps.storage import CollectionRepo, VideoRepo
        if not VideoRepo(_db(request)).get(video_id):
            raise HTTPException(status_code=404, detail="视频不存在")
        ids = CollectionRepo(_db(request)).set_memberships(video_id, body.collection_ids)
    return {"ok": True, "collection_ids": ids}


@router.post("/videos/{video_id}/collections/{cid}/toggle")
def toggle_video_collection(video_id: str, cid: str, request: Request):
    with request.app.state.db_lock:
        from apps.storage import CollectionRepo, VideoRepo
        if not VideoRepo(_db(request)).get(video_id):
            raise HTTPException(status_code=404, detail="视频不存在")
        repo = CollectionRepo(_db(request))
        if not repo.get(cid):
            raise HTTPException(status_code=404, detail="收藏夹不存在")
        on = repo.toggle(video_id, cid)
        ids = repo.collection_ids_for_video(video_id)
    return {"ok": True, "in_collection": on, "collection_ids": ids}


# ---------------- 收藏计数（兼容旧接口） ----------------
@router.get("/favorites/count")
def favorites_count(request: Request):
    with request.app.state.db_lock:
        return {"ok": True, "count": VideoRepo(_db(request)).favorite_count()}


class FavIn(BaseModel):
    favorite: bool = True


@router.post("/videos/{video_id}/favorite")
def set_favorite(video_id: str, body: FavIn, request: Request):
    with request.app.state.db_lock:
        vrepo = VideoRepo(_db(request))
        if not vrepo.get(video_id):
            raise HTTPException(status_code=404, detail="视频不存在")
        vrepo.set_favorite(video_id, body.favorite)
        return {"ok": True, "favorite": body.favorite, "count": vrepo.favorite_count()}


# ---------------- 批量导入 ----------------
class BatchIn(BaseModel):
    sources: list[str]
    max_height: int | None = None
    auto_asr: bool = True
    auto_punctuate: bool = True
    allow_over_threshold: bool = False


@router.post("/intake/batch")
async def intake_batch(body: BatchIn, request: Request):
    """批量导入：每个来源创建一个后台任务，立即返回任务 id 列表。"""
    from apps.api_s3 import IntakeIn, _run_intake

    st = request.app.state
    sources = [s.strip() for s in body.sources if s and s.strip()]
    if not sources:
        raise HTTPException(status_code=400, detail="请至少提供一个链接或文件路径")
    if len(sources) > 20:
        raise HTTPException(status_code=400, detail="单次最多 20 条")

    # 容量阈值拦截
    with st.db_lock:
        info = get_storage(st.db, st.settings.data_root, _threshold(request))
    if info["warn"] and not body.allow_over_threshold:
        raise HTTPException(
            status_code=409,
            detail=f"磁盘使用率 {info['used_pct']}% 已超过阈值 {info['threshold']}%，"
                   f"请先清理或扩容（可在确认后强制导入）")

    job_ids = []
    for src in sources:
        payload = IntakeIn(source=src, max_height=body.max_height,
                           auto_asr=body.auto_asr, auto_punctuate=body.auto_punctuate)
        jid = st.jobs.create(stage="排队中", payload=payload.model_dump())
        asyncio.create_task(_run_intake(request.app, jid, payload))
        job_ids.append(jid)
    return {"ok": True, "task_ids": job_ids, "count": len(job_ids),
            "storage": {"used_pct": info["used_pct"], "threshold": info["threshold"],
                        "warn": info["warn"]}}


# ---------------- 任务控制 ----------------
@router.post("/tasks/{task_id}/pause")
def task_pause(task_id: str, request: Request):
    j = request.app.state.jobs.control(task_id, "pause")
    if not j:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"ok": True, "task": j}


@router.post("/tasks/{task_id}/resume")
def task_resume(task_id: str, request: Request):
    j = request.app.state.jobs.control(task_id, "resume")
    if not j:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"ok": True, "task": j}


@router.post("/tasks/{task_id}/cancel")
def task_cancel(task_id: str, request: Request):
    j = request.app.state.jobs.control(task_id, "cancel")
    if not j:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"ok": True, "task": j}


@router.delete("/tasks/{task_id}")
def task_delete(task_id: str, request: Request):
    j = request.app.state.jobs.get(task_id)
    if not j:
        raise HTTPException(status_code=404, detail="任务不存在")
    request.app.state.jobs.delete(task_id)
    return {"ok": True}


class BatchDelIn(BaseModel):
    ids: list[str]


@router.post("/tasks/batch-delete")
def tasks_batch_delete(body: BatchDelIn, request: Request):
    n = request.app.state.jobs.delete_many(body.ids or [])
    return {"ok": True, "deleted": n}


@router.post("/tasks/{task_id}/retry")
async def task_retry(task_id: str, request: Request):
    """重试：用原任务参数重新跑一遍。"""
    from apps.api_s3 import IntakeIn, _run_intake

    st = request.app.state
    j = st.jobs.get(task_id)
    if not j:
        raise HTTPException(status_code=404, detail="任务不存在")
    payload = j.get("payload") or {}
    if not payload.get("source"):
        raise HTTPException(status_code=400, detail="该任务没有可重试的来源")
    body = IntakeIn(**payload)
    st.jobs.update(task_id, status="running", stage="重新排队", progress=0,
                   control="running", _clear=("error", "result"))
    asyncio.create_task(_run_intake(request.app, task_id, body))
    return {"ok": True, "task_id": task_id}


# ---------------- 视频问答（SSE 流式） ----------------
class QaIn(BaseModel):
    question: str
    caption_id: str | None = None


@router.post("/videos/{video_id}/qa")
async def video_qa(video_id: str, body: QaIn, request: Request):
    st = request.app.state
    if not st.settings.llm_api_key:
        raise HTTPException(status_code=400, detail="未配置 LLM API Key，无法问答")
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    with st.db_lock:
        vrepo, crepo, srepo = VideoRepo(st.db), SourceCaptionRepo(st.db), SegmentRepo(st.db)
        video = vrepo.get(video_id)
        if not video:
            raise HTTPException(status_code=404, detail="视频不存在")
        caption_id = body.caption_id
        if not caption_id:
            primary = CaptionIntake(vrepo, crepo, srepo).choose_primary(video_id)
            caption_id = primary["id"] if primary else None
        cues = srepo.for_video(video_id, caption_id) if caption_id else []

    if not cues:
        raise HTTPException(status_code=400, detail="该视频还没有字幕，无法问答")

    context = build_qa_context(cues, question)
    user = build_user_prompt(video["title"], context, question)
    llm = getattr(st, "llm", None)
    if llm is None:
        from apps.core.ai import LLMConfig, OpenAICompatibleLLM
        llm = OpenAICompatibleLLM(LLMConfig(
            base_url=st.settings.llm_base_url, api_key=st.settings.llm_api_key,
            model=st.settings.llm_model))
        st.llm = llm

    async def event_stream():
        acc = []
        try:
            async for delta in llm.stream_text(QA_SYSTEM, user):
                acc.append(delta)
                yield f"data: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
            cites = extract_citations("".join(acc))
            yield f"data: {json.dumps({'done': True, 'citations': cites}, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001
            log.warning("QA 流式失败: %s", str(e)[:200])
            yield f"data: {json.dumps({'error': str(e)[:200]}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
