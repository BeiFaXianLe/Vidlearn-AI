"""V2 增强功能测试：磁盘容量 / 收藏 / 批量导入 / 任务控制 / 问答辅助。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

from apps.core.qa import build_qa_context, build_user_prompt, extract_citations, fmt_ms
from apps.core.storage_info import get_storage


@pytest.fixture()
def client():
    import importlib
    import apps.main as main_mod
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c:
        yield c


def _mk_video(client, title="t", pid="p1"):
    db = client.app.state.db
    from apps.storage import MediaAssetRepo, VideoRepo
    with client.app.state.db_lock:
        v = VideoRepo(db).upsert(platform="local", platform_video_id=pid, title=title, duration_ms=60000)
        MediaAssetRepo(db).add(video_id=v["id"], asset_type="original_media",
                              storage_path=str(Path(__file__)), sha256=pid + "x" * 60,
                              size_bytes=1024 * 1024)
    return v["id"]


# ---------- 磁盘容量 ----------
def test_storage_endpoint(client):
    r = client.get("/api/storage")
    assert r.status_code == 200
    d = r.json()
    for k in ("total_bytes", "used_bytes", "free_bytes", "used_pct", "threshold",
              "warn", "danger", "breakdown", "top_videos"):
        assert k in d
    assert isinstance(d["breakdown"]["video"], int)
    assert 50 <= d["threshold"] <= 99


def test_threshold_update_and_bounds(client):
    assert client.put("/api/storage/threshold", json={"threshold": 90}).json()["threshold"] == 90
    # 越界被夹紧
    assert client.put("/api/storage/threshold", json={"threshold": 10}).json()["threshold"] == 50
    assert client.put("/api/storage/threshold", json={"threshold": 200}).json()["threshold"] == 99
    client.put("/api/storage/threshold", json={"threshold": 85})


def test_video_list_has_size_and_favorite(client):
    _mk_video(client, "视频A", "pa")
    v = client.get("/api/videos").json()["videos"][0]
    assert "size_bytes" in v and "favorite" in v


# ---------- 收藏 ----------
def test_favorite_toggle_and_count(client):
    vid = _mk_video(client, "收藏测试", "pf")
    r = client.post(f"/api/videos/{vid}/favorite", json={"favorite": True})
    assert r.json()["favorite"] is True and r.json()["count"] >= 1
    assert client.get("/api/favorites/count").json()["count"] >= 1
    client.post(f"/api/videos/{vid}/favorite", json={"favorite": False})
    assert client.post(f"/api/videos/{vid}/favorite", json={"favorite": True}).status_code == 200


def test_favorite_404(client):
    assert client.post("/api/videos/nope/favorite", json={"favorite": True}).status_code == 404


# ---------- 批量导入 ----------
def test_batch_rejects_empty(client):
    assert client.post("/api/intake/batch", json={"sources": []}).status_code == 400


def test_batch_rejects_too_many(client):
    r = client.post("/api/intake/batch", json={"sources": ["x"] * 21})
    assert r.status_code == 400


def test_batch_creates_tasks(client, tmp_path):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"x" * 100)
    r = client.post("/api/intake/batch", json={"sources": [str(f)]})
    # 允许 200（创建任务）或 409（磁盘阈值）
    assert r.status_code in (200, 409)


# ---------- 任务控制 ----------
def test_task_control_404(client):
    for action in ("pause", "resume", "cancel", "retry"):
        assert client.post(f"/api/tasks/nope/{action}").status_code == 404


def test_jobstore_control_and_pause_flag():
    from apps.core.jobs import JobStore
    js = JobStore()
    jid = js.create(payload={"source": "x"})
    assert js.get(jid)["control"] == "running"
    assert js.control(jid, "pause")["control"] == "paused"
    assert js.is_paused(jid) is True
    js.control(jid, "resume")
    assert js.is_paused(jid) is False
    js.control(jid, "cancel")
    assert js.is_cancelled(jid) is True


# ---------- 问答辅助 ----------
def test_qa_context_selects_relevant_and_bounds():
    cues = [{"start_ms": i * 1000, "end_ms": i * 1000 + 900, "text": f"第{i}段 内容{i}"} for i in range(100)]
    cues[50]["text"] = "这里讲 Redis 持久化的 RDB 快照"
    ctx = build_qa_context(cues, "RDB 快照是什么", max_chars=2000)
    assert "Redis 持久化" in ctx
    assert len(ctx) <= 4000


def test_qa_context_empty():
    assert build_qa_context([], "问题") == ""


def test_extract_citations_unique_and_ordered():
    text = "见【0:14】和【7:44】，另外【0:14】重复"
    assert extract_citations(text) == ["00:14", "07:44"]


def test_fmt_ms():
    assert fmt_ms(65000) == "1:05"
    assert fmt_ms(0) == "0:00"


def test_build_user_prompt_contains_parts():
    p = build_user_prompt("标题", "[0:00] 内容", "问题？")
    assert "标题" in p and "内容" in p and "问题？" in p and "【mm:ss】" in p


# ---------- 任务回填标题（任务面板与视频对应） ----------
def test_task_carries_title_and_video_id(client):
    from apps.api_s3 import _set_job
    app = client.app
    jid = app.state.jobs.create(stage="排队中", payload={"source": "https://x"})
    _set_job(app, jid, title="示例视频标题", video_id="vid-1")
    d = client.get(f"/api/tasks/{jid}").json()
    assert d["title"] == "示例视频标题"
    assert d["video_id"] == "vid-1"
    assert d["payload"]["source"] == "https://x"


# ---------- 媒体失效重新导入 ----------
def test_reimport_missing_video_404(client):
    r = client.post("/api/videos/not-exist/reimport")
    assert r.status_code == 404


def test_reimport_without_source_400(client):
    vid = _mk_video(client)          # 本地视频无 source_url
    r = client.post(f"/api/videos/{vid}/reimport")
    assert r.status_code == 400


def test_reimport_starts_task(client, monkeypatch):
    import asyncio
    from apps.storage import VideoRepo

    url = "https://www.bilibili.com/video/BV1x"
    with client.app.state.db_lock:
        v = VideoRepo(client.app.state.db).upsert(
            platform="bilibili", platform_video_id="bv-x", title="失效视频", source_url=url)

    # 不真正下载：拦截 create_task，关闭协程即可
    monkeypatch.setattr(asyncio, "create_task", lambda coro: coro.close())

    body = client.post(f"/api/videos/{v['id']}/reimport").json()
    assert body["ok"] is True and body["task_id"]
    d = client.get(f"/api/tasks/{body['task_id']}").json()
    assert d["payload"]["source"] == url
