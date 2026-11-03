"""S5 API：AI 内容分析（摘要/章节/知识点）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from apps.core.ai import LLMConfig, OpenAICompatibleLLM
from apps.core.analysis import AnalysisService
from apps.core.logging_setup import get_logger
from apps.storage import SegmentRepo, SourceCaptionRepo, VideoRepo
from apps.storage.analysis_repos import ChapterRepo, KnowledgePointRepo, SummaryRepo

router = APIRouter(prefix="/api", tags=["s5"])
log = get_logger("analysis-api")


def _svc(request: Request):
    st = request.app.state
    db = st.db
    llm = getattr(st, "llm", None)
    if llm is None:
        cfg = LLMConfig(
            base_url=st.settings.llm_base_url,
            api_key=st.settings.llm_api_key,
            model=st.settings.llm_model,
        )
        llm = OpenAICompatibleLLM(cfg)
        st.llm = llm
    return AnalysisService(VideoRepo(db), SegmentRepo(db), SummaryRepo(db),
                           ChapterRepo(db), KnowledgePointRepo(db), llm)


class SumIn(BaseModel):
    video_id: str
    mode: str = "quick"
    caption_id: str | None = None
    content_scope: str = "unknown"


class ChapIn(BaseModel):
    video_id: str
    caption_id: str | None = None


@router.post("/analysis/summary")
async def summary(body: SumIn, request: Request):
    st = request.app.state
    try:
        with st.db_lock:
            s = await _svc(request).summarize(body.video_id, mode=body.mode,
                                              caption_id=body.caption_id,
                                              content_scope=body.content_scope,
                                              model=st.settings.llm_model)
        return {"ok": True, "summary": {"id": s["id"], "mode": s["mode"],
                                        "content": s["content"], "scope": s["content_scope"]}}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # LLMError 等
        raise HTTPException(status_code=502, detail=f"分析失败: {e}")


@router.post("/analysis/chapters")
async def chapters(body: ChapIn, request: Request):
    st = request.app.state
    try:
        with st.db_lock:
            chs = await _svc(request).build_chapters(body.video_id,
                                                     caption_id=body.caption_id,
                                                     model=st.settings.llm_model)
        return {"ok": True, "chapters": chs}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"分析失败: {e}")


@router.post("/analysis/points")
async def points(body: ChapIn, request: Request):
    st = request.app.state
    try:
        with st.db_lock:
            pts = await _svc(request).build_points(body.video_id,
                                                   caption_id=body.caption_id,
                                                   model=st.settings.llm_model)
        return {"ok": True, "knowledge_points": pts}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"分析失败: {e}")


@router.get("/analysis/status")
def analysis_status(request: Request):
    st = request.app.state
    return {"ok": True, "llm_configured": bool(st.settings.llm_api_key),
            "model": st.settings.llm_model,
            "base_url": st.settings.llm_base_url}


@router.get("/videos/{video_id}/summary")
def get_summary(video_id: str, request: Request, mode: str | None = None):
    db = request.app.state.db
    s = SummaryRepo(db).latest(video_id, mode)
    return {"ok": True, "summary": s}


@router.get("/videos/{video_id}/chapters")
def get_chapters(video_id: str, request: Request):
    db = request.app.state.db
    return {"ok": True, "chapters": ChapterRepo(db).for_video(video_id)}


@router.get("/videos/{video_id}/knowledge-points")
def get_points(video_id: str, request: Request):
    db = request.app.state.db
    return {"ok": True, "knowledge_points": KnowledgePointRepo(db).for_video(video_id)}
