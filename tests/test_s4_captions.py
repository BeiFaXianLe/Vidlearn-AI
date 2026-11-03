"""字幕三级回退与后台任务注册表测试。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.core.jobs import JobStore


# ---------------- JobStore ----------------
def test_job_lifecycle():
    js = JobStore()
    jid = js.create(stage="排队中")
    j = js.get(jid)
    assert j["status"] == "running" and j["progress"] == 0
    js.update(jid, stage="下载中", progress=40)
    js.update(jid, status="done", result={"ok": 1})
    j = js.get(jid)
    assert j["stage"] == "下载中" and j["progress"] == 40
    assert j["status"] == "done" and j["result"]["ok"] == 1


def test_job_update_ignores_none_and_missing():
    js = JobStore()
    jid = js.create()
    js.update(jid, stage=None, progress=10)     # None 不覆盖
    assert js.get(jid)["stage"] == "排队中"
    assert js.get(jid)["progress"] == 10
    js.update("nonexistent", progress=5)       # 不报错
    assert js.get("nonexistent") is None


def test_job_prune_keeps_latest():
    js = JobStore()
    ids = [js.create() for _ in range(120)]
    js.prune(keep=50)
    assert len(js.list(limit=200)) <= 50
    assert js.get(ids[-1]) is not None


# ---------------- 字幕来源优先级 ----------------
def test_source_priority_prefers_human_over_ai_over_asr():
    from apps.core.intake import SOURCE_PRIORITY
    assert SOURCE_PRIORITY["bilibili_human"] < SOURCE_PRIORITY["bilibili_ai"]
    assert SOURCE_PRIORITY["bilibili_ai"] < SOURCE_PRIORITY["embedded"]
    assert SOURCE_PRIORITY["embedded"] < SOURCE_PRIORITY["asr"]


def test_auto_asr_field_default_true():
    from apps.api_s3 import IntakeIn
    body = IntakeIn(source="x")
    assert body.auto_asr is True
    assert IntakeIn(source="x", auto_asr=False).auto_asr is False


def test_asr_status_reports_model_readiness():
    from fastapi.testclient import TestClient
    import importlib
    import apps.main as main_mod
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c:
        r = c.get("/api/asr/status")
        assert r.status_code == 200
        assert r.json()["model_ready"] is True  # models/faster-whisper-small 已预置


def test_asr_endpoint_returns_task_id():
    """ASR 提交应立即返回 task_id（不阻塞）。"""
    from fastapi.testclient import TestClient
    import importlib
    import apps.main as main_mod
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c:
        # 造一个带媒体资产的视频（媒体路径需真实存在）
        db = c.app.state.db
        import uuid as _uuid
        from apps.storage import MediaAssetRepo, VideoRepo
        media = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "media" / "sample_no_sub.mp4"
        assert media.exists(), "测试样本缺失"
        with c.app.state.db_lock:
            v = VideoRepo(db).upsert(platform="local",
                                     platform_video_id="x-" + _uuid.uuid4().hex[:8],
                                     title="t")
            MediaAssetRepo(db).add(video_id=v["id"], asset_type="original_media",
                                  storage_path=str(media),
                                  sha256=_uuid.uuid4().hex)
        r = c.post("/api/asr", json={"video_id": v["id"]})
        assert r.status_code == 200
        assert r.json()["task_id"]
        assert r.json()["async"] is True
