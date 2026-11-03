"""S8 安全测试：路径穿越、凭证脱敏、非法输入、Range 越界。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

from apps.core.credentials import parse_cookie, redact
from apps.storage import MediaAssetRepo, VideoRepo


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDLEARN_DATA_ROOT", str(tmp_path))
    import importlib
    import apps.main as main_mod
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c:
        yield c


def _mk_video_with_asset(client, tmp_path, path: str):
    app = client.app
    with app.state.db_lock:
        v = VideoRepo(app.state.db).upsert(platform="local", platform_video_id="p", title="t", duration_ms=1000)
        MediaAssetRepo(app.state.db).add(video_id=v["id"], asset_type="original_media",
                                         storage_path=path, sha256="a" * 64)
    return v["id"]


# ---------- 路径穿越 ----------
def test_media_rejects_path_outside_data_root(client, tmp_path):
    # 资产路径指向 data_root 之外
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("secret")
    vid = _mk_video_with_asset(client, tmp_path, str(outside))
    r = client.get(f"/api/videos/{vid}/media")
    assert r.status_code == 403


def test_media_missing_file(client, tmp_path):
    vid = _mk_video_with_asset(client, tmp_path, str(tmp_path / "nope.mp4"))
    r = client.get(f"/api/videos/{vid}/media")
    assert r.status_code == 404


# ---------- Range 越界 ----------
def test_media_range_bad(client, tmp_path):
    f = tmp_path / "media" / "original" / "a.mp4"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"0123456789")
    vid = _mk_video_with_asset(client, tmp_path, str(f))
    r = client.get(f"/api/videos/{vid}/media", headers={"Range": "bytes=99999-"})
    assert r.status_code == 416
    r2 = client.get(f"/api/videos/{vid}/media", headers={"Range": "bytes=abc"})
    assert r2.status_code == 416


# ---------- 凭证脱敏 ----------
def test_redact_multiple_keys():
    msg = "SESSDATA=abc123; ttwid=xyz; msToken=mmm; normal=ok"
    out = redact(msg)
    assert "abc123" not in out and "xyz" not in out and "mmm" not in out
    assert "normal=ok" in out


def test_parse_cookie_no_crash_on_garbage():
    assert parse_cookie(";;;===") == {}
    assert parse_cookie("justtext") == {"SESSDATA": "justtext"}


# ---------- 非法 media 上传路径（intake 不接受任意服务器路径的越权访问，仅本地适配器读路径）----------
def test_video_detail_404(client):
    r = client.get("/api/videos/nonexistent")
    assert r.status_code == 404


def test_health_ok(client):
    r = client.get("/api/health")
    assert r.json()["status"] == "ok"
