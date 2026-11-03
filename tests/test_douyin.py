"""抖音适配器测试（mock yt-dlp/ffprobe，不依赖真实网络）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.adapters import resolve_adapter
from apps.adapters.base import AcquireError, ErrorCode, FetchOpts
from apps.adapters.douyin import DouyinAdapter, normalize_douyin_url


def test_can_handle():
    import asyncio
    ad = DouyinAdapter()
    assert asyncio.run(ad.can_handle("https://v.douyin.com/iRxAbcDe/"))
    assert asyncio.run(ad.can_handle("https://www.douyin.com/video/7345678901234567890"))
    assert not asyncio.run(ad.can_handle("https://www.bilibili.com/video/BV1xx411c7mD"))


def test_normalize_share_text():
    s = "7.99 xyz:/ 复制打开抖音，看看作品 https://v.douyin.com/iRxAbcDe/ 好看"
    assert normalize_douyin_url(s) == "https://v.douyin.com/iRxAbcDe/"


def test_resolve_routes_douyin():
    ad = resolve_adapter("https://v.douyin.com/iRxAbcDe/")
    assert ad.name == "douyin"


def test_probe_parses_json(monkeypatch):
    payload = {
        "id": "7345678901234567890",
        "title": "测试抖音标题",
        "uploader": "某作者",
        "duration": 15.2,
        "thumbnail": "https://x/y.jpg",
        "formats": [{"height": 1920}, {"height": 720}],
        "webpage_url": "https://www.douyin.com/video/7345678901234567890",
        "extractor": "Douyin",
    }

    async def fake_run(arg, timeout=0):
        return 0, json.dumps(payload), ""

    monkeypatch.setattr("apps.adapters.douyin.run_cmd", fake_run)
    import asyncio
    meta = asyncio.run(DouyinAdapter().probe("https://v.douyin.com/x/"))
    assert meta.platform == "douyin"
    assert meta.platform_video_id == "7345678901234567890"
    assert meta.title == "测试抖音标题"
    assert meta.duration_ms == 15200
    assert meta.available_heights == [1920, 720]


def test_probe_login_error(monkeypatch):
    async def fake_run(arg, timeout=0):
        return 1, "", "ERROR: This video requires login. Please provide cookies."

    monkeypatch.setattr("apps.adapters.douyin.run_cmd", fake_run)
    import asyncio
    with pytest.raises(AcquireError) as e:
        asyncio.run(DouyinAdapter().probe("https://v.douyin.com/x/"))
    assert e.value.code == ErrorCode.NEED_LOGIN


def test_probe_blocked_error(monkeypatch):
    async def fake_run(arg, timeout=0):
        return 1, "", "ERROR: 403 Forbidden risk verify captcha"
    monkeypatch.setattr("apps.adapters.douyin.run_cmd", fake_run)
    import asyncio
    with pytest.raises(AcquireError) as e:
        asyncio.run(DouyinAdapter().probe("https://v.douyin.com/x/"))
    assert e.value.code == ErrorCode.BLOCKED


def test_fetch_media(tmp_path, monkeypatch):
    async def fake_run(args, timeout=0):
        # 模拟 yt-dlp 产物
        (tmp_path / "734.mp4").write_bytes(b"FAKEMP4DATA")
        return 0, "", ""

    async def fake_ffprobe(path, ffprobe):
        return {"format": {"format_name": "mov,mp4,m4a", "duration": "5.0"},
                "streams": [{"codec_type": "video", "codec_name": "h264", "width": 720, "height": 1280},
                            {"codec_type": "audio", "codec_name": "aac"}]}

    monkeypatch.setattr("apps.adapters.douyin.run_cmd", fake_run)
    monkeypatch.setattr("apps.adapters.douyin.ffprobe_json", fake_ffprobe)
    import asyncio
    res = asyncio.run(DouyinAdapter().fetch_media(
        "https://v.douyin.com/x/", FetchOpts(out_dir=tmp_path)))
    assert res.file_path.name == "734.mp4"
    assert res.height == 1280 and res.vcodec == "h264"
    assert res.has_audio is True
    assert res.declared_duration_ms == 5000
    assert len(res.sha256) == 64


def test_cookie_file_controlled_dir(tmp_path):
    class Cred:
        def get(self, platform):
            return {"ttwid": "abc", "sessionid": "xyz"} if platform == "douyin" else None

    ad = DouyinAdapter(cookie_provider=Cred(), cookie_tmp_dir=tmp_path / "cookies")
    p = ad._new_cookie_file()
    assert ad._write_cookie_file(p) is True
    text = p.read_text(encoding="utf-8")
    assert ".douyin.com" in text and "ttwid" in text
    assert p.parent == (tmp_path / "cookies")


def test_no_cookie_when_anonymous(tmp_path):
    ad = DouyinAdapter(cookie_provider=None, cookie_tmp_dir=tmp_path / "c")
    assert ad._cookie_header() is None


def test_browser_cookie_flag(monkeypatch):
    captured = {}

    async def fake_run(args, timeout=0):
        captured["args"] = args
        return 0, json.dumps({"id": "1", "title": "t", "formats": []}), ""

    monkeypatch.setattr("apps.adapters.douyin.run_cmd", fake_run)
    import asyncio
    ad = DouyinAdapter(cookies_from_browser="edge", cookie_provider=None)
    asyncio.run(ad.probe("https://v.douyin.com/x/"))
    assert "--cookies-from-browser" in captured["args"]
    assert "edge" in captured["args"]
