"""S5 API 扩展：字幕标点恢复（后台任务）。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from apps.core.ai import LLMConfig, OpenAICompatibleLLM
from apps.core.intake import CaptionIntake
from apps.core.logging_setup import get_logger
from apps.core.punctuation import restore_punctuation
from apps.storage import MediaAssetRepo, SegmentRepo, SourceCaptionRepo, VideoRepo

router = APIRouter(prefix="/api", tags=["s5"])
log = get_logger("punctuation")


class PunctuateIn(BaseModel):
    video_id: str
    caption_id: str | None = None   # 不传则对主字幕轨处理


def _llm(st):
    """st = app.state"""
    if not hasattr(st, "llm"):
        st.llm = OpenAICompatibleLLM(LLMConfig(
            base_url=st.settings.llm_base_url,
            api_key=st.settings.llm_api_key,
            model=st.settings.llm_model))
    return st.llm


@router.post("/analysis/punctuate")
async def punctuate(body: PunctuateIn, request: Request):
    """为字幕补标点（存为派生轨，不覆盖原始字幕）。"""
    st = request.app.state
    if not st.settings.llm_api_key:
        raise HTTPException(status_code=400, detail="未配置 LLM API Key，无法恢复标点")
    db = st.db
    with st.db_lock:
        vrepo, arepo, crepo, srepo = (VideoRepo(db), MediaAssetRepo(db),
                                      SourceCaptionRepo(db), SegmentRepo(db))
        if not vrepo.get(body.video_id):
            raise HTTPException(status_code=404, detail="视频不存在")
        caption_id = body.caption_id
        if not caption_id:
            primary = CaptionIntake(vrepo, crepo, srepo).choose_primary(body.video_id)
            if not primary:
                raise HTTPException(status_code=400, detail="该视频没有字幕")
            caption_id = primary["id"]
        cues = srepo.for_video(body.video_id, caption_id)
    if not cues:
        raise HTTPException(status_code=400, detail="字幕轨为空")

    job_id = st.jobs.create(stage="准备中")
    asyncio.create_task(_run_punctuate(st, job_id, body.video_id, caption_id, cues))
    return {"ok": True, "task_id": job_id, "async": True}


async def _run_punctuate(st, job_id: str, video_id: str, caption_id: str, cues: list[dict]):
    db = st.db
    try:
        st.jobs.update(job_id, stage="恢复标点", progress=15)
        res = await restore_punctuation(cues, _llm(st))
        st.jobs.update(job_id, stage="写入派生字幕轨", progress=85)
        with st.db_lock:
            cap = CaptionIntake(VideoRepo(db), SourceCaptionRepo(db), SegmentRepo(db)).add_track(
                video_id=video_id, source_type="asr_punct", language="zh",
                cues=res["cues"], is_ai_generated=True,
                completeness="complete", fmt="json")
        st.jobs.update(job_id, stage="完成", progress=100, status="done", result={
            "changed": res["changed"], "total": res["total"],
            "failed": res["failed"], "caption_id": cap["id"],
            "segments": cap["segment_count"],
            "sample": res["cues"][:2] if res["cues"] else [],
        })
    except Exception as e:  # noqa: BLE001
        st.jobs.update(job_id, status="error", stage="失败",
                       error={"code": "punctuation_failed", "message": str(e)[:300]})
