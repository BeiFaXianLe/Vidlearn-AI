"""S4 API：本地 ASR 转写并入库（后台任务 + 进度）。"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from apps.core.asr import FasterWhisperASR, ASROpts
from apps.core.intake import CaptionIntake
from apps.core.logging_setup import get_logger
from apps.storage import (
    MediaAssetRepo,
    SegmentRepo,
    SourceCaptionRepo,
    VideoRepo,
)

router = APIRouter(prefix="/api", tags=["s4"])
log = get_logger("asr")


def _repos(request: Request):
    db = request.app.state.db
    return (VideoRepo(db), MediaAssetRepo(db), SourceCaptionRepo(db), SegmentRepo(db))


class AsrIn(BaseModel):
    video_id: str
    media_path: str | None = None     # 不传则取该视频的 original_media
    model: str | None = None
    language: str = "zh"
    segment_sec: int = 30
    overlap_sec: int = 2


@router.post("/asr")
async def run_asr(body: AsrIn, request: Request):
    """提交 ASR 任务，立即返回 task_id；前端轮询 /api/tasks/{id}。"""
    st = request.app.state
    with st.db_lock:
        vrepo, arepo, crepo, srepo = _repos(request)
        video = vrepo.get(body.video_id)
        if not video:
            raise HTTPException(status_code=404, detail="视频不存在")
        if body.media_path:
            media = Path(body.media_path)
        else:
            assets = [a for a in arepo.for_video(body.video_id)
                      if a["asset_type"] == "original_media"]
            if not assets:
                raise HTTPException(status_code=400, detail="该视频没有可用的原始媒体")
            media = Path(sorted(assets, key=lambda a: a["created_at"])[-1]["storage_path"])
        asset_id = sorted(assets, key=lambda a: a["created_at"])[-1]["id"] if assets else None
    if not media.exists():
        raise HTTPException(status_code=404, detail=f"媒体文件不存在: {media}")

    job_id = st.jobs.create(stage="准备中")
    asyncio.create_task(_run_asr(st, job_id, body, media, asset_id))
    return {"ok": True, "task_id": job_id, "async": True}


async def _run_asr(st, job_id: str, body: AsrIn, media: Path, asset_id: str | None):
    db = st.db
    opts = ASROpts(
        language=body.language,
        model=body.model or st.settings.asr_model,
        device=st.settings.asr_device,
        compute_type=st.settings.asr_compute_type,
        segment_sec=body.segment_sec,
        overlap_sec=body.overlap_sec,
    )
    try:
        st.jobs.update(job_id, stage="提取音频", progress=5)
        provider = FasterWhisperASR(ffmpeg=st.settings.ffmpeg_path,
                                    model_dir=st.settings.asr_model_dir or None,
                                    work_dir=str(st.settings.media.audio_work))
        st.jobs.update(job_id, stage="语音识别中", progress=20)
        result = await provider.transcribe(media, opts)
        log.info("ASR 完成 cues=%d rtf=%s status=%s", len(result.cues), result.rtf, result.status)

        cap_info = None
        if result.cues:
            with st.db_lock:
                cap = CaptionIntake(VideoRepo(db), SourceCaptionRepo(db), SegmentRepo(db)).add_track(
                    video_id=body.video_id, source_type="asr", language=opts.language,
                    cues=result.cues, is_ai_generated=True,
                    completeness="complete" if result.status == "complete" else "partial",
                    fmt="json", media_asset_id=asset_id)
            cap_info = {"id": cap["id"], "segments": cap["segment_count"]}

        st.jobs.update(job_id, stage="完成", progress=100, status="done", result={
            "asr": {"status": result.status, "model": result.model, "rtf": result.rtf,
                    "cues": len(result.cues), "reason": result.reason},
            "caption": cap_info,
            "first": result.cues[:3] if result.cues else [],
        })
    except Exception as e:  # noqa: BLE001
        st.jobs.update(job_id, status="error", stage="失败",
                       error={"code": "asr_failed", "message": str(e)[:300]})


@router.get("/asr/status")
def asr_status(request: Request):
    """返回 ASR 模型配置与是否已预置（不做实际加载）。"""
    st = request.app.state
    # 复用 ASR 引擎的模型定位逻辑，避免两处判断不一致
    provider = FasterWhisperASR(model_dir=st.settings.asr_model_dir or None)
    resolved = provider.resolve_model(st.settings.asr_model)
    from pathlib import Path as _P
    p = _P(resolved)
    ready = (p / "model.bin").exists() if p.is_absolute() else None
    return {"ok": True, "model": st.settings.asr_model, "device": st.settings.asr_device,
            "compute_type": st.settings.asr_compute_type, "model_ready": bool(ready),
            "model_path": str(p) if ready else None}
