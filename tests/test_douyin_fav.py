"""抖音收藏夹读取（登录态批量导入）离线单元测试。

不依赖真实浏览器/网络：解析函数、适配器错误映射、接口层都用 mock。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.adapters.base import AcquireError, ErrorCode
from apps.adapters.douyin import DouyinAdapter
from apps.core import douyin_browser


# ---------------- 解析层 ----------------
def test_parse_collect_folders_shape():
    payload = {
        "status_code": 0,
        "collects_infos": [
            {"collects_id": "701", "collects_name": "默认收藏", "total_number": 12,
             "cover_url": "http://c.jpg"},
            {"collects_id": "", "collects_name": "无ID应跳过", "total_number": 1},
            {"collects_id": "702", "collects_name": "教程", "total_number": 3},
        ],
    }
    folders = douyin_browser._parse_collect_folders(payload)
    assert [f["id"] for f in folders] == ["701", "702"]
    assert folders[0]["title"] == "默认收藏" and folders[0]["count"] == 12


def test_parse_collect_folders_alternate_fields():
    # 兼容不同版本字段名
    payload = {"data": {"collects": [
        {"collect_id": "9", "name": "另一个", "count": 4},
    ]}}
    folders = douyin_browser._parse_collect_folders(payload)
    assert folders == [{"id": "9", "title": "另一个", "count": 4, "cover": ""}]


def test_parse_collect_videos_skips_invalid():
    payload = {
        "has_more": True,
        "cursor": 20,
        "aweme_list": [
            {"aweme_id": "111", "desc": "视频一", "author": {"nickname": "作者A"},
             "video": {"duration": 61000, "cover": {"url_list": ["http://c1.jpg"]}}},
            {"desc": "无 id 跳过"},
            {"aweme_id": "222", "desc": "", "author": {"nickname": "作者B"},
             "video": {"duration": 120000}},
        ],
    }
    r = douyin_browser._parse_collect_videos(payload)
    assert r["has_more"] is True and r["cursor"] == 20
    assert [it["aweme_id"] for it in r["items"]] == ["111", "222"]
    assert r["items"][0]["title"] == "视频一"
    assert r["items"][0]["duration_ms"] == 61000
    assert r["items"][0]["author"] == "作者A"
    assert r["items"][0]["url"] == "https://www.douyin.com/video/111"
    assert r["items"][1]["title"] == "抖音视频"  # 空 desc 兜底


def test_parse_collect_videos_empty():
    r = douyin_browser._parse_collect_videos({})
    assert r["items"] == [] and r["has_more"] is False


# ---------------- 分页（fetch_collect_videos） ----------------
def _vpage(*ids, has_more=True, cursor=0):
    return {
        "has_more": has_more,
        "cursor": cursor,
        "aweme_list": [
            {"aweme_id": i, "desc": f"视频{i}", "author": {"nickname": "A"},
             "video": {"duration": 1000}}
            for i in ids
        ],
    }


@pytest.mark.asyncio
async def test_fetch_collect_videos_page0(monkeypatch):
    monkeypatch.setattr(douyin_browser, "playwright_available", lambda: True)

    async def fake_pages(url, need_index, **kw):
        return [_vpage("1", "2", has_more=True), _vpage("3", "4", has_more=False)]

    monkeypatch.setattr(douyin_browser, "_open_collect_videos_pages", fake_pages)
    r = await douyin_browser.fetch_collect_videos("999", cursor=0)
    assert [it["aweme_id"] for it in r["items"]] == ["1", "2"]
    assert r["cursor"] == 1
    assert r["has_more"] is True


@pytest.mark.asyncio
async def test_fetch_collect_videos_page1(monkeypatch):
    monkeypatch.setattr(douyin_browser, "playwright_available", lambda: True)

    async def fake_pages(url, need_index, **kw):
        # need_index=1 → 会滚动到第 2 页
        assert need_index == 1
        return [_vpage("1", "2", has_more=True), _vpage("3", "4", has_more=False)]

    monkeypatch.setattr(douyin_browser, "_open_collect_videos_pages", fake_pages)
    r = await douyin_browser.fetch_collect_videos("999", cursor=1)
    assert [it["aweme_id"] for it in r["items"]] == ["3", "4"]
    assert r["cursor"] == 2
    assert r["has_more"] is False


@pytest.mark.asyncio
async def test_fetch_collect_videos_out_of_range_returns_empty(monkeypatch):
    monkeypatch.setattr(douyin_browser, "playwright_available", lambda: True)

    async def fake_pages(url, need_index, **kw):
        return [_vpage("1", has_more=False)]

    monkeypatch.setattr(douyin_browser, "_open_collect_videos_pages", fake_pages)
    r = await douyin_browser.fetch_collect_videos("999", cursor=5)
    assert r["items"] == [] and r["has_more"] is False


@pytest.mark.asyncio
async def test_fetch_collect_videos_has_more_via_next_page(monkeypatch):
    """本页 has_more 缺失但已截获后续页时仍应报告 has_more=True。"""
    monkeypatch.setattr(douyin_browser, "playwright_available", lambda: True)

    async def fake_pages(url, need_index, **kw):
        return [{"aweme_list": [{"aweme_id": "1"}]},   # 无 has_more 字段
                {"aweme_list": [{"aweme_id": "2"}]}]

    monkeypatch.setattr(douyin_browser, "_open_collect_videos_pages", fake_pages)
    r = await douyin_browser.fetch_collect_videos("999", cursor=0)
    assert r["has_more"] is True
    assert r["cursor"] == 1


@pytest.mark.asyncio
async def test_fetch_collect_videos_need_login(monkeypatch):
    monkeypatch.setattr(douyin_browser, "playwright_available", lambda: True)

    async def fake_pages(url, need_index, **kw):
        return []

    monkeypatch.setattr(douyin_browser, "_open_collect_videos_pages", fake_pages)
    with pytest.raises(douyin_browser.DouyinResolveError) as ei:
        await douyin_browser.fetch_collect_videos("999")
    assert ei.value.kind == "need_login"


# ---------------- 适配器层 ----------------
class _FakeCookieProvider:
    def __init__(self, cookies):
        self._cookies = cookies

    def get(self, platform):
        return dict(self._cookies) if self._cookies else None


def _adapter(cookies=None, use_browser=True, profile_dir=""):
    return DouyinAdapter(cookie_provider=_FakeCookieProvider(cookies),
                         use_browser=use_browser, profile_dir=profile_dir)


@pytest.mark.asyncio
async def test_fetch_fav_folders_ok(monkeypatch):
    monkeypatch.setattr(douyin_browser, "playwright_available", lambda: True)

    async def fake_folders(**kw):
        return {"user": "抖音用户", "folders": [{"id": "1", "title": "默认", "count": 5}]}

    monkeypatch.setattr(douyin_browser, "fetch_collect_folders", fake_folders)
    a = _adapter({"ttwid": "x", "sessionid": "y"})
    r = await a.fetch_fav_folders()
    assert r["user"] == "抖音用户"
    assert r["folders"][0]["count"] == 5


@pytest.mark.asyncio
async def test_fetch_fav_folders_need_login(monkeypatch):
    monkeypatch.setattr(douyin_browser, "playwright_available", lambda: True)

    async def fake_folders(**kw):
        raise douyin_browser.DouyinResolveError("need_login", "未登录")

    monkeypatch.setattr(douyin_browser, "fetch_collect_folders", fake_folders)
    a = _adapter({"ttwid": "x"})
    with pytest.raises(AcquireError) as ei:
        await a.fetch_fav_folders()
    assert ei.value.code == ErrorCode.NEED_LOGIN


@pytest.mark.asyncio
async def test_fetch_fav_items_ok(monkeypatch):
    monkeypatch.setattr(douyin_browser, "playwright_available", lambda: True)
    seen = {}

    async def fake_videos(collects_id, *, cursor=0, count=20, **kw):
        seen["cid"] = collects_id
        seen["cursor"] = cursor
        return {"items": [{"aweme_id": "1", "title": "t", "duration_ms": 1000}],
                "has_more": True, "cursor": 20}

    monkeypatch.setattr(douyin_browser, "fetch_collect_videos", fake_videos)
    a = _adapter({"ttwid": "x"})
    r = await a.fetch_fav_items("999", cursor=0)
    assert seen["cid"] == "999"
    assert r["has_more"] is True and r["cursor"] == 20
    assert r["items"][0]["aweme_id"] == "1"


@pytest.mark.asyncio
async def test_fetch_fav_items_blocked(monkeypatch):
    monkeypatch.setattr(douyin_browser, "playwright_available", lambda: True)

    async def fake_videos(*a, **kw):
        raise douyin_browser.DouyinResolveError("blocked", "风控")

    monkeypatch.setattr(douyin_browser, "fetch_collect_videos", fake_videos)
    a = _adapter({"ttwid": "x"})
    with pytest.raises(AcquireError) as ei:
        await a.fetch_fav_items("1")
    assert ei.value.code == ErrorCode.BLOCKED


@pytest.mark.asyncio
async def test_browser_disabled_requires_browser(monkeypatch):
    monkeypatch.setattr(douyin_browser, "playwright_available", lambda: False)
    a = _adapter({"ttwid": "x"}, use_browser=False)
    with pytest.raises(AcquireError) as ei:
        await a.fetch_fav_folders()
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


def test_douyin_fav_folders_endpoint(client, monkeypatch):
    import apps.api_s2 as s2

    async def fake(self):
        return {"user": "u", "folders": [{"id": "1", "title": "默认", "count": 3}]}

    monkeypatch.setattr(s2.DouyinAdapter, "fetch_fav_folders", fake)
    r = client.get("/api/douyin/fav/folders")
    body = r.json()
    assert r.status_code == 200 and body["ok"] is True
    assert body["folders"][0]["title"] == "默认"


def test_douyin_fav_items_endpoint_error_passthrough(client, monkeypatch):
    import apps.api_s2 as s2

    async def fake(self, collects_id, **kw):
        raise AcquireError(ErrorCode.NEED_LOGIN, "未登录抖音，无法读取收藏夹")

    monkeypatch.setattr(s2.DouyinAdapter, "fetch_fav_items", fake)
    r = client.get("/api/douyin/fav/items?collects_id=1")
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "need_login"
