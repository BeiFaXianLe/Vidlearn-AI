"""S3 API：媒体入库、完整性报告、字幕轨道与分段。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from apps.adapters import resolve_adapter
from apps.adapters.base import AcquireError
from apps.core.acquire import AcquisitionManager
from apps.core.integrity import check_media
from apps.core.intake import CaptionIntake, MediaIntake
from apps.storage import (
    MediaAssetRepo,
    SegmentRepo,
    SourceCaptionRepo,
    VideoRepo,
)

router = APIRouter(prefix="/api", tags=["s3"])


def _db(request: Request):
    return request.app.state.db


def _repos(request: Request):
    db = _db(request)
    return (VideoRepo(db), MediaAssetRepo(db), SourceCaptionRepo(db), SegmentRepo(db))


class IntakeIn(BaseModel):
    source: str
    max_height: int | None = None
    download_sections: str | None = None
    purpose: str = "playback"      # playback | asr
    also_subtitles: bool = True
    auto_asr: bool = True          # 无平台/内嵌字幕时自动本地 ASR 兜底
    auto_punctuate: bool = True    # ASR 字幕自动补标点（需 LLM Key）


async def _run_punctuate(app, video_id: str) -> dict:
    """对主字幕轨补标点，写入派生轨 asr_punct。"""
    st = app.state
    db = st.db
    from apps.core.intake import CaptionIntake
    from apps.core.punctuation import restore_punctuation
    from apps.storage import SegmentRepo, SourceCaptionRepo, VideoRepo

    try:
        vrepo, crepo, srepo = VideoRepo(db), SourceCaptionRepo(db), SegmentRepo(db)
        with st.db_lock:
            primary = CaptionIntake(vrepo, crepo, srepo).choose_primary(video_id)
            if not primary:
                return {"cues": 0, "reason": "无字幕轨"}
            cues = srepo.for_video(video_id, primary["id"])
        if not cues:
            return {"cues": 0, "reason": "字幕轨为空"}
        from apps.core.ai import LLMConfig, OpenAICompatibleLLM
        llm = OpenAICompatibleLLM(LLMConfig(
            base_url=st.settings.llm_base_url,
            api_key=st.settings.llm_api_key,
            model=st.settings.llm_model))
        res = await restore_punctuation(cues, llm)
        if not res["changed"]:
            return {"cues": 0, "reason": "未获得有效标点结果"}
        with st.db_lock:
            CaptionIntake(vrepo, crepo, srepo).add_track(
                video_id=video_id, source_type="asr_punct", language="zh",
                cues=res["cues"], is_ai_generated=True,
                completeness="complete", fmt="json")
        return {"cues": res["changed"], "changed": res["changed"]}
    except Exception as e:  # noqa: BLE001
        return {"cues": 0, "reason": f"标点恢复失败: {str(e)[:160]}"}


async def _run_asr(app, video_id: str, media_path: Path, asset_id: str | None) -> dict:
    """对已入库媒体跑本地 ASR，并把结果作为 asr 字幕轨入库。"""
    st = app.state
    db = st.db
    from apps.core.asr import ASROpts, FasterWhisperASR
    from apps.core.intake import CaptionIntake
    from apps.storage import SegmentRepo, SourceCaptionRepo, VideoRepo

    try:
        provider = FasterWhisperASR(ffmpeg=st.settings.ffmpeg_path,
                                    model_dir=st.settings.asr_model_dir or None,
                                    work_dir=str(st.settings.media.audio_work))
        # 术语热词注入（L1）：把该视频相关术语作为 initial_prompt
        try:
            from apps.storage import GlossaryRepo
            with st.db_lock:
                _terms = GlossaryRepo(db).resolved_terms(video_id)
            _prompt = "、".join(t["term"] for t in _terms[:60]) if _terms else None
        except Exception:
            _prompt = None
        opts = ASROpts(model=st.settings.asr_model, device=st.settings.asr_device,
                       compute_type=st.settings.asr_compute_type,
                       segment_sec=st.settings.asr_segment_sec,
                       overlap_sec=st.settings.asr_overlap_sec,
                       initial_prompt=_prompt)
        result = await provider.transcribe(media_path, opts)
        if not result.cues:
            return {"cues": 0, "reason": result.reason or "ASR 无输出"}
        with st.db_lock:
            CaptionIntake(VideoRepo(db), SourceCaptionRepo(db), SegmentRepo(db)).add_track(
                video_id=video_id, source_type="asr", language=opts.language,
                cues=result.cues, is_ai_generated=True,
                completeness="complete" if result.status == "complete" else "partial",
                fmt="json", media_asset_id=asset_id)
        return {"cues": len(result.cues), "rtf": result.rtf, "status": result.status}
    except Exception as e:  # noqa: BLE001
        return {"cues": 0, "reason": f"ASR 失败: {str(e)[:200]}"}


@router.post("/intake")
async def intake(body: IntakeIn, request: Request):
    """异步入库：立即返回 task_id，前端轮询 /api/tasks/{id} 看进度。

    流程：探测 → 下载/remux → 完整性 → 入库 → 平台字幕 → 内嵌字幕 → 分段。
    """
    import asyncio

    st = request.app.state
    job_id = st.jobs.create(stage="排队中", payload=body.model_dump())
    asyncio.create_task(_run_intake(request.app, job_id, body))
    return {"ok": True, "task_id": job_id, "async": True}


def _set_job(app, job_id, *, stage=None, progress=None, status=None,
             result=None, error=None, title=None, video_id=None):
    app.state.jobs.update(job_id, stage=stage, progress=progress, status=status,
                          result=result, error=error, title=title, video_id=video_id)


class TaskCancelled(Exception):
    pass


async def _checkpoint(app, job_id: str) -> None:
    """阶段边界检查点：支持暂停（等待）与取消（抛异常）。"""
    import asyncio as _asyncio
    while app.state.jobs.is_paused(job_id):
        await _asyncio.sleep(0.4)
    if app.state.jobs.is_cancelled(job_id):
        raise TaskCancelled()


async def _run_intake(app, job_id: str, body: IntakeIn):
    st = app.state
    db = st.db
    vrepo, arepo, crepo, srepo = (VideoRepo(db), MediaAssetRepo(db),
                                  SourceCaptionRepo(db), SegmentRepo(db))
    cred = getattr(st, "cred", None)
    if cred is None:
        from apps.core.credentials import FileCredentialProvider
        cred = FileCredentialProvider(st.settings.data_root / "credentials")
        st.cred = cred
    try:
        await _checkpoint(app, job_id)
        _set_job(app, job_id, stage="解析链接/文件", progress=8)
        ad = resolve_adapter(body.source, yt_dlp=st.settings.yt_dlp_path,
                             ffprobe=st.settings.ffprobe_path, cookie_provider=cred,
                             cookie_tmp_dir=st.settings.media.temp / "cookies")
        meta = await ad.probe(body.source)
        with st.db_lock:
            video = MediaIntake(vrepo, arepo).register_video(meta)
        # 任务一旦探明标题就回填，供前端任务面板显示（与视频卡片对应）
        _set_job(app, job_id, title=video["title"], video_id=video["id"])
        await _checkpoint(app, job_id)
        _set_job(app, job_id, stage="下载媒体", progress=20)

        mgr = AcquisitionManager(st.settings.media.temp, st.settings.media.original,
                                 st.settings.ffmpeg_path)
        res = await mgr.acquire(ad, body.source, max_height=body.max_height,
                                download_sections=body.download_sections)
        await _checkpoint(app, job_id)
        _set_job(app, job_id, stage="完整性校验", progress=60)

        rep = await check_media(res.file_path, ffprobe=st.settings.ffprobe_path,
                                ffmpeg=st.settings.ffmpeg_path, purpose=body.purpose)
        with st.db_lock:
            asset = MediaIntake(vrepo, arepo).attach_media(
                video["id"], res, integrity_verdict=rep.verdict, acquired_from=ad.name)
        await _checkpoint(app, job_id)
        _set_job(app, job_id, stage="获取字幕", progress=75)

        caption_info = None
        if body.also_subtitles and hasattr(ad, "fetch_subtitles"):
            sub = await ad.fetch_subtitles(body.source)
            if sub.get("chosen"):
                from apps.core.subtitles import cues_from_bilibili, normalize_cues
                from apps.core.textnorm import simplify_cues
                c = sub["chosen"]
                cues = simplify_cues(normalize_cues(cues_from_bilibili(c)))
                with st.db_lock:
                    cap = CaptionIntake(vrepo, crepo, srepo).add_track(
                        video_id=video["id"], source_type=c["source"], language=c.get("lang"),
                        cues=cues, is_ai_generated=c.get("is_ai", False),
                        completeness="complete", fmt="json", media_asset_id=asset["id"])
                caption_info = {"source": c["source"], "cues": len(cues),
                                "segments": cap["segment_count"]}
            else:
                caption_info = {"source": None, "reason": sub.get("reason")}

        if caption_info is None or (caption_info and caption_info.get("source") is None):
            await _checkpoint(app, job_id)
            _set_job(app, job_id, stage="提取内嵌字幕", progress=85)
            from apps.core.subtitles import extract_embedded_subtitles, normalize_cues
            embedded = await extract_embedded_subtitles(
                res.file_path, st.settings.media.subtitles,
                ffmpeg=st.settings.ffmpeg_path, ffprobe=st.settings.ffprobe_path)
            added = []
            for tr in embedded:
                if not tr.get("cues"):
                    continue
                from apps.core.textnorm import simplify_cues
                cues = simplify_cues(normalize_cues(tr["cues"]))
                with st.db_lock:
                    cap = CaptionIntake(vrepo, crepo, srepo).add_track(
                        video_id=video["id"], source_type="embedded",
                        language=tr.get("language"), cues=cues, is_ai_generated=False,
                        completeness="complete", fmt="srt",
                        source_path=str(tr.get("path") or ""), media_asset_id=asset["id"])
                added.append({"language": tr.get("language"), "cues": len(cues),
                              "segments": cap["segment_count"]})
            if added:
                caption_info = {"source": "embedded", "tracks": added}

        # 3) 仍无字幕 → 本地 ASR 兜底（PRD §4.3 三级回退）
        if (caption_info is None or caption_info.get("source") is None) and body.auto_asr:
            if res.has_audio:
                await _checkpoint(app, job_id)
                _set_job(app, job_id, stage="本地语音识别（ASR）", progress=88)
                asr_info = await _run_asr(app, video["id"], res.file_path, asset["id"])
                if asr_info.get("cues"):
                    caption_info = {"source": "asr", "cues": asr_info["cues"],
                                    "rtf": asr_info.get("rtf")}
                else:
                    caption_info = {"source": None,
                                    "reason": asr_info.get("reason") or "ASR 未产生字幕"}
            else:
                caption_info = {"source": None, "reason": "媒体无音轨，无法 ASR"}

        # 4) ASR 字幕 → 补标点（派生轨，原始字幕保留）
        if (body.auto_punctuate and caption_info
                and caption_info.get("source") == "asr"
                and st.settings.llm_api_key):
            await _checkpoint(app, job_id)
            _set_job(app, job_id, stage="恢复字幕标点", progress=95)
            punct_info = await _run_punctuate(app, video["id"])
            if punct_info.get("cues"):
                caption_info = {"source": "asr_punct", "cues": punct_info["cues"],
                                "punctuated": punct_info.get("changed")}

        _set_job(app, job_id, stage="完成", progress=100, status="done", result={
            "video": {"id": video["id"], "title": video["title"],
                      "duration_ms": video["duration_ms"]},
            "media": {"path": str(res.file_path), "height": res.height,
                      "vcodec": res.vcodec, "sha256": res.sha256},
            "integrity": {"verdict": rep.verdict, "reasons": rep.reasons},
            "captions": caption_info,
        })
    except TaskCancelled:
        _set_job(app, job_id, status="cancelled", stage="已取消")
    except AcquireError as e:
        _set_job(app, job_id, status="error", stage="失败",
                 error={"code": e.code.value, "message": e.message})
    except Exception as e:  # noqa: BLE001
        _set_job(app, job_id, status="error", stage="失败",
                 error={"code": "internal", "message": str(e)[:300]})


@router.post("/videos/{video_id}/reimport")
async def reimport_video(video_id: str, request: Request):
    """媒体失效/缺失时，用原来源地址重新导入（重新下载 + 校验 + 入库）。"""
    import asyncio

    st = request.app.state
    with st.db_lock:
        video = VideoRepo(st.db).get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="视频不存在")
    source = video.get("source_url")
    if not source:
        raise HTTPException(
            status_code=400,
            detail="该视频没有原平台链接，无法自动重新导入；请通过「导入视频」重新添加本地文件")
    body = IntakeIn(source=source)
    job_id = st.jobs.create(stage="排队中", payload=body.model_dump())
    asyncio.create_task(_run_intake(request.app, job_id, body))
    return {"ok": True, "task_id": job_id}


@router.get("/tasks/{task_id}")
def task_status(task_id: str, request: Request):
    j = request.app.state.jobs.get(task_id)
    if not j:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"ok": True, **j}


@router.get("/tasks")
def task_list(request: Request, limit: int = 20):
    return {"ok": True, "tasks": request.app.state.jobs.list(limit)}


@router.get("/integrity")
async def integrity(path: str, request: Request, purpose: str = "playback"):
    st = request.app.state
    p = Path(path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    rep = await check_media(p, ffprobe=st.settings.ffprobe_path,
                            ffmpeg=st.settings.ffmpeg_path, purpose=purpose)
    return {"ok": True, "verdict": rep.verdict, "reasons": rep.reasons, "checks": rep.checks}


@router.get("/videos")
def list_videos(request: Request, limit: int = 50, favorite: bool | None = None,
                collection: str | None = None):
    with request.app.state.db_lock:
        vrepo = _repos(request)[0]
        return {"ok": True,
                "videos": vrepo.list_with_size(limit, favorite=favorite, collection_id=collection)}


@router.get("/videos/{video_id}")
def video_detail(video_id: str, request: Request):
    with request.app.state.db_lock:
        vrepo, arepo, crepo, srepo = _repos(request)
        v = vrepo.get(video_id)
        if not v:
            raise HTTPException(status_code=404, detail="视频不存在")
        assets = arepo.for_video(video_id)
        caps = crepo.for_video(video_id)
        primary = CaptionIntake(vrepo, crepo, srepo).choose_primary(video_id)
        segs = srepo.for_video(video_id, primary["id"]) if primary else []
    return {"ok": True, "video": v, "media_assets": assets,
            "caption_tracks": caps, "primary_caption": primary,
            "segments": segs[:200]}


@router.get("/videos/{video_id}/transcript")
def video_transcript(video_id: str, request: Request, caption_id: str | None = None):
    with request.app.state.db_lock:
        vrepo, arepo, crepo, srepo = _repos(request)
        if not vrepo.get(video_id):
            raise HTTPException(status_code=404, detail="视频不存在")
        if caption_id is None:
            primary = CaptionIntake(vrepo, crepo, srepo).choose_primary(video_id)
            caption_id = primary["id"] if primary else None
        segs = srepo.for_video(video_id, caption_id) if caption_id else []
    if not caption_id:
        return {"ok": True, "segments": []}
    return {"ok": True, "caption_id": caption_id, "segments": segs}


