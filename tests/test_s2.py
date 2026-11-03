"""S2 自测：本地文件适配器 / B站适配器 / 字幕强校验 / 下载管理。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.adapters import resolve_adapter
from apps.adapters._util import run_cmd
from apps.adapters.base import AcquireError, ErrorCode, FetchOpts, VideoMeta


TS = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "media"


# ---------- 本地文件 ----------
@pytest.mark.asyncio
async def test_local_probe():
    a = resolve_adapter(str(TS / "sample_no_sub.mp4"))
    meta = await a.probe(str(TS / "sample_no_sub.mp4"))
    assert meta.platform == "local"
    assert meta.duration_ms > 1000
    assert meta.has_subtitle_tracks is False
    assert meta.extra["has_audio"] is True


@pytest.mark.asyncio
async def test_local_probe_mkv_has_subtitle_track():
    a = resolve_adapter(str(TS / "sample_with_sub.mkv"))
    meta = await a.probe(str(TS / "sample_with_sub.mkv"))
    assert meta.has_subtitle_tracks is True


@pytest.mark.asyncio
async def test_local_fetch(tmp_path):
    a = resolve_adapter(str(TS / "sample_no_sub.mp4"))
    res = await a.fetch_media(str(TS / "sample_no_sub.mp4"), FetchOpts(out_dir=tmp_path))
    assert res.file_path.exists()
    assert len(res.sha256) == 64
    assert res.height == 360
    assert res.has_audio is True


@pytest.mark.asyncio
async def test_local_reject_fake(tmp_path):
    fake = tmp_path / "x.mp4"
    fake.write_text("not a video")
    a = resolve_adapter(str(fake))
    with pytest.raises(AcquireError) as ei:
        await a.probe(str(fake))
    assert ei.value.code == ErrorCode.MEDIA_INVALID


# ---------- 来源识别 ----------
def test_resolve_adapter_bilibili():
    a = resolve_adapter("https://www.bilibili.com/video/BV1dJ7C6FEUX")
    assert a.name == "bilibili"


def test_resolve_adapter_unsupported():
    with pytest.raises(AcquireError) as ei:
        resolve_adapter("https://example.com/xyz")
    assert ei.value.code == ErrorCode.UNSUPPORTED_URL


# ---------- B站字幕解析与校验（离线单元，构造假数据） ----------
def _mk_adapter():
    from apps.adapters.bilibili import BilibiliAdapter
    return BilibiliAdapter(refetch_attempts=2)


@pytest.mark.asyncio
async def test_pick_valid_cue_rejects_overflow():
    """末条超出视频时长 → 判为污染，返回 None。"""
    a = _mk_adapter()
    subs = [{"lan": "ai-zh", "ai_type": 0, "subtitle_url": "http://x"}]
    # 伪造 _api_get：返回越界字幕
    async def fake_api(url, cookie):
        return {"body": [{"from": 0.0, "to": 300.0, "content": "错位"}]}
    a._api_get = fake_api
    picked = await a._pick_valid_cue(subs, duration_ms=100000, cookie=None)
    assert picked is None


@pytest.mark.asyncio
async def test_pick_valid_cue_accepts_and_converts_ms():
    a = _mk_adapter()
    subs = [{"lan": "ai-zh", "ai_type": 0, "subtitle_url": "//aisub"}]
    async def fake_api(url, cookie):
        return {"body": [{"from": 1.5, "to": 3.0, "content": "你好"},
                         {"from": 60.0, "to": 62.0, "content": "结尾"}]}
    a._api_get = fake_api
    # 时长 70s，字幕覆盖 1.5~62s（>50%），应通过
    picked = await a._pick_valid_cue(subs, duration_ms=70000, cookie=None)
    assert picked is not None
    assert picked["source"] == "bilibili_ai"
    assert picked["cues"][0]["start_ms"] == 1500
    assert picked["cues"][0]["end_ms"] == 3000


@pytest.mark.asyncio
async def test_pick_valid_cue_rejects_low_coverage():
    """时间戳合法但只覆盖很短片段 → 判为不完整/污染，拒绝。"""
    a = _mk_adapter()
    subs = [{"lan": "ai-zh", "ai_type": 0, "subtitle_url": "//aisub"}]
    async def fake_api(url, cookie):
        return {"body": [{"from": 1.5, "to": 3.0, "content": "片段"}]}
    a._api_get = fake_api
    picked = await a._pick_valid_cue(subs, duration_ms=100000, cookie=None)
    assert picked is None


# ---------- 错误分类 ----------
def test_classify_premium():
    a = _mk_adapter()
    e = a._classify("ERROR: Format(s) 1080P are missing; you have to become a premium member", "")
    assert e.code == ErrorCode.NOT_AUTHORIZED


def test_classify_network():
    a = _mk_adapter()
    e = a._classify("Connection reset by peer timeout", "")
    assert e.code == ErrorCode.NETWORK
    assert e.retryable is True


def test_classify_unsupported():
    a = _mk_adapter()
    e = a._classify("ERROR: Unsupported URL: https://x", "")
    assert e.code == ErrorCode.UNSUPPORTED_URL

