"""自定义收藏夹测试。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    import importlib
    import apps.main as main_mod
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c:
        yield c


def _mk_video(client, title="视频", pid="p"):
    db = client.app.state.db
    from apps.storage import VideoRepo
    with client.app.state.db_lock:
        v = VideoRepo(db).upsert(platform="local", platform_video_id=pid, title=title, duration_ms=1000)
    return v["id"]


# ---------- 收藏夹 CRUD ----------
def test_create_list_rename_delete_collection(client):
    r = client.post("/api/collections", json={"name": "后端架构"})
    assert r.status_code == 200
    cid = r.json()["collection"]["id"]
    names = [c["name"] for c in client.get("/api/collections").json()["collections"]]
    assert "后端架构" in names

    r2 = client.patch(f"/api/collections/{cid}", json={"name": "后端"})
    assert r2.json()["collection"]["name"] == "后端"

    assert client.delete(f"/api/collections/{cid}").status_code == 200
    names = [c["name"] for c in client.get("/api/collections").json()["collections"]]
    assert "后端" not in names


def test_create_duplicate_returns_same(client):
    a = client.post("/api/collections", json={"name": "重复夹"}).json()["collection"]["id"]
    b = client.post("/api/collections", json={"name": "重复夹"}).json()["collection"]["id"]
    assert a == b


def test_create_empty_name_rejected(client):
    assert client.post("/api/collections", json={"name": "  "}).status_code == 400


def test_rename_to_existing_rejected(client):
    client.post("/api/collections", json={"name": "A夹"})
    b = client.post("/api/collections", json={"name": "B夹"}).json()["collection"]["id"]
    assert client.patch(f"/api/collections/{b}", json={"name": "A夹"}).status_code == 400


def test_collection_404s(client):
    assert client.patch("/api/collections/nope", json={"name": "x"}).status_code == 404
    assert client.delete("/api/collections/nope").status_code == 404


# ---------- 归属 ----------
def test_toggle_membership_and_count(client):
    vid = _mk_video(client, "归属测试", "pv1")
    cid = client.post("/api/collections", json={"name": "待看"}).json()["collection"]["id"]

    r = client.post(f"/api/videos/{vid}/collections/{cid}/toggle")
    assert r.json()["in_collection"] is True
    assert cid in r.json()["collection_ids"]

    # 收藏数 +1
    assert client.get("/api/favorites/count").json()["count"] >= 1
    # 收藏夹列表 count 正确
    cols = {c["id"]: c for c in client.get("/api/collections").json()["collections"]}
    assert cols[cid]["count"] >= 1

    # 再次 toggle 取消
    r2 = client.post(f"/api/videos/{vid}/collections/{cid}/toggle")
    assert r2.json()["in_collection"] is False
    assert cid not in r2.json()["collection_ids"]


def test_set_memberships_multi(client):
    vid = _mk_video(client, "多夹", "pv2")
    c1 = client.post("/api/collections", json={"name": "夹1"}).json()["collection"]["id"]
    c2 = client.post("/api/collections", json={"name": "夹2"}).json()["collection"]["id"]
    r = client.put(f"/api/videos/{vid}/collections", json={"collection_ids": [c1, c2]})
    assert set(r.json()["collection_ids"]) == {c1, c2}
    # 视频列表带 collection_ids
    vids = {v["id"]: v for v in client.get("/api/videos").json()["videos"]}
    assert c1 in (vids[vid]["collection_ids"] or "")
    # 覆盖为空
    r2 = client.put(f"/api/videos/{vid}/collections", json={"collection_ids": []})
    assert r2.json()["collection_ids"] == []


def test_filter_videos_by_collection(client):
    vid = _mk_video(client, "筛选", "pv3")
    cid = client.post("/api/collections", json={"name": "筛选夹"}).json()["collection"]["id"]
    client.put(f"/api/videos/{vid}/collections", json={"collection_ids": [cid]})
    vids = client.get(f"/api/videos?collection={cid}").json()["videos"]
    assert any(v["id"] == vid for v in vids)


def test_delete_collection_keeps_video(client):
    vid = _mk_video(client, "删夹保视频", "pv4")
    cid = client.post("/api/collections", json={"name": "临时夹"}).json()["collection"]["id"]
    client.put(f"/api/videos/{vid}/collections", json={"collection_ids": [cid]})
    client.delete(f"/api/collections/{cid}")
    # 视频仍在
    assert client.get(f"/api/videos/{vid}").status_code == 200


def test_legacy_favorite_maps_to_default_collection(client):
    vid = _mk_video(client, "旧收藏兼容", "pv5")
    client.post(f"/api/videos/{vid}/favorite", json={"favorite": True})
    cols = client.get("/api/collections").json()["collections"]
    assert any(c["name"] == "默认收藏" for c in cols)
    r = client.get(f"/api/videos/{vid}/collections")
    assert len(r.json()["collection_ids"]) >= 1
