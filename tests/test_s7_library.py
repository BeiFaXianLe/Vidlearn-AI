"""S7 测试：进度、笔记、导出、删除、统计。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

from apps.storage import VideoRepo, init_db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDLEARN_DATA_ROOT", str(tmp_path))
    # 清掉可能的模块级缓存，重新构建 app
    import importlib
    import apps.main as main_mod
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c:
        yield c


def _mk_video(client):
    """直接通过 app.state.db 造一个视频，避免真实下载。"""
    app = client.app
    with app.state.db_lock:
        v = VideoRepo(app.state.db).upsert(
            platform="local", platform_video_id="test1", title="测试视频", duration_ms=10000)
    return v["id"]


def test_progress_roundtrip(client):
    vid = _mk_video(client)
    r = client.put(f"/api/videos/{vid}/progress", json={"position_ms": 5000, "duration_ms": 10000})
    assert r.status_code == 200
    r = client.get(f"/api/videos/{vid}/progress")
    assert r.json()["progress"]["position_ms"] == 5000
    # 完成
    client.put(f"/api/videos/{vid}/progress", json={"position_ms": 9800, "duration_ms": 10000})
    assert client.get(f"/api/videos/{vid}/progress").json()["progress"]["completed"] == 1


def test_notes_crud(client):
    vid = _mk_video(client)
    r = client.post(f"/api/videos/{vid}/notes", json={"content": "我的笔记", "start_ms": 3000})
    assert r.status_code == 200
    notes = client.get(f"/api/videos/{vid}/notes").json()["notes"]
    assert len(notes) == 1 and notes[0]["content"] == "我的笔记"


def test_export_markdown(client):
    vid = _mk_video(client)
    client.post(f"/api/videos/{vid}/notes", json={"content": "笔记X"})
    r = client.get(f"/api/videos/{vid}/export.md")
    assert r.status_code == 200
    assert "测试视频" in r.text
    assert "我的笔记" in r.text or "笔记X" in r.text
    assert r.headers["content-type"].startswith("text/markdown")


def test_stats(client):
    _mk_video(client)
    r = client.get("/api/stats")
    assert r.status_code == 200
    assert r.json()["videos"] >= 1


def test_delete_video_keep_knowledge(client):
    vid = _mk_video(client)
    r = client.delete(f"/api/videos/{vid}?delete_media=false&delete_knowledge=false")
    assert r.status_code == 200
    # 视频仍在（仅标记无媒体）
    assert client.get(f"/api/videos/{vid}").status_code == 200


def test_delete_video_full(client):
    vid = _mk_video(client)
    r = client.delete(f"/api/videos/{vid}?delete_media=true&delete_knowledge=true")
    assert r.status_code == 200
    assert client.get(f"/api/videos/{vid}").status_code == 404
