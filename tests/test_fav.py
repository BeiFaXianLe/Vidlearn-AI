"""B站收藏夹读取（登录态批量导入）离线单元测试。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.adapters.base import AcquireError, ErrorCode
from apps.adapters.bilibili import BilibiliAdapter


class _FakeCookieProvider:
    def __init__(self, cookies):
        self._cookies = cookies

    def get(self, platform):
        return dict(self._cookies) if self._cookies else None


def _adapter(cookies=None):
    return BilibiliAdapter(cookie_provider=_FakeCookieProvider(cookies))


@pytest.mark.asyncio
async def test_fav_folders_parses_and_sends_mid():
    a = _adapter({"SESSDATA": "abc", "DedeUserID": "42"})
    seen = {}

    async def fake_api(url, cookie):
        seen["cookie"] = cookie
        if "nav" in url:
            return {"code": 0, "data": {"isLogin": True, "mid": 42, "uname": "小明"}}
        if "list-all" in url:
            assert "up_mid=42" in url
            return {"code": 0, "data": {"list": [
                {"id": 1001, "title": "默认收藏", "media_count": 2},
                {"id": 1002, "title": "教程", "media_count": 7},
            ]}}
        raise AssertionError("unexpected url " + url)

    a._api_get = fake_api
    r = await a.fetch_fav_folders()
    assert r["mid"] == 42
    assert r["uname"] == "小明"
    assert [f["id"] for f in r["folders"]] == ["1001", "1002"]
    assert r["folders"][1]["count"] == 7
    assert "SESSDATA=abc" in seen["cookie"]


@pytest.mark.asyncio
async def test_fav_folders_requires_cookie():
    a = _adapter(None)
    with pytest.raises(AcquireError) as ei:
        await a.fetch_fav_folders()
    assert ei.value.code == ErrorCode.NEED_LOGIN


@pytest.mark.asyncio
async def test_fav_folders_rejects_not_logged_in():
    a = _adapter({"SESSDATA": "expired"})

    async def fake_api(url, cookie):
        return {"code": 0, "data": {"isLogin": False}}

    a._api_get = fake_api
    with pytest.raises(AcquireError) as ei:
        await a.fetch_fav_folders()
    assert ei.value.code == ErrorCode.NEED_LOGIN


@pytest.mark.asyncio
async def test_fav_items_parses_and_skips_invalid():
    a = _adapter({"SESSDATA": "abc"})

    async def fake_api(url, cookie):
        assert "media_id=1001" in url and "pn=1" in url
        return {"code": 0, "data": {
            "info": {"title": "默认收藏", "media_count": 3},
            "has_more": True,
            "medias": [
                {"bvid": "BV1xx", "title": "视频一", "duration": 61,
                 "upper": {"name": "UP主"}, "cover": "c"},
                {"title": "已失效视频"},              # 无 bvid → 跳过
                {"bvid": "BV2yy", "title": "视频二", "duration": 120},
            ],
        }}

    a._api_get = fake_api
    r = await a.fetch_fav_items("1001", pn=1)
    assert r["has_more"] is True
    assert r["count"] == 3
    assert [it["bvid"] for it in r["items"]] == ["BV1xx", "BV2yy"]
    assert r["items"][0]["author"] == "UP主"
    assert r["items"][1]["duration_s"] == 120


@pytest.mark.asyncio
async def test_fav_items_api_error_raises():
    a = _adapter({"SESSDATA": "abc"})

    async def fake_api(url, cookie):
        return {"code": -101, "message": "账号未登录"}

    a._api_get = fake_api
    with pytest.raises(AcquireError) as ei:
        await a.fetch_fav_items("1001")
    assert ei.value.code == ErrorCode.INTERNAL


# ---------------- 接口层 ----------------
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDLEARN_DATA_ROOT", str(tmp_path))
    import importlib
    import apps.main as main_mod
    importlib.reload(main_mod)
    from fastapi.testclient import TestClient
    with TestClient(main_mod.app) as c:
        yield c


def test_fav_folders_endpoint(client, monkeypatch):
    import apps.api_s2 as s2

    async def fake(self):
        return {"mid": 1, "uname": "u", "folders": [{"id": "1", "title": "默认", "count": 3}]}

    monkeypatch.setattr(s2.BilibiliAdapter, "fetch_fav_folders", fake)
    r = client.get("/api/bilibili/fav/folders")
    body = r.json()
    assert r.status_code == 200
    assert body["ok"] is True
    assert body["folders"][0]["title"] == "默认"


def test_fav_items_endpoint_error_passthrough(client, monkeypatch):
    import apps.api_s2 as s2

    async def fake(self, media_id, **kw):
        raise AcquireError(ErrorCode.NEED_LOGIN, "未配置 Cookie，无法读取收藏夹")

    monkeypatch.setattr(s2.BilibiliAdapter, "fetch_fav_items", fake)
    r = client.get("/api/bilibili/fav/items?media_id=1")
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "need_login"
