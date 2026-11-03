"""S3-02/03 媒体完整性 + S3-08 字幕覆盖率 自测。

使用 data/testset 下真实样本：
  sample_no_sub.mp4      正常（有音轨/视频）
  sample_truncated.mp4   截断（moov 缺失）
  sample_with_sub.mkv    MKV（内嵌字幕，流级 duration 为 null）
  sample_no_audio.mp4    无音轨 MP4
  sample_fake.mp4        伪装 .mp4（文本，容器无法解析）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.core.integrity import IntegrityReport, check_cues, check_media

TS = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "media"


# ----------------------------- check_media -----------------------------
@pytest.mark.asyncio
async def test_normal_mp4_verified():
    r = await check_media(TS / "sample_no_sub.mp4")
    assert isinstance(r, IntegrityReport)
    assert r.verdict == "verified", r.reasons
    assert r.checks["container_parse"] is True
    assert r.checks["has_video"] is True
    assert r.checks["has_audio"] is True
    assert r.checks["full_decode"] is True
    assert r.checks["tail_decode"] is True


@pytest.mark.asyncio
async def test_truncated_mp4_invalid():
    r = await check_media(TS / "sample_truncated.mp4")
    assert r.verdict == "invalid", r.reasons
    assert r.checks["container_parse"] is False


@pytest.mark.asyncio
async def test_fake_mp4_invalid():
    r = await check_media(TS / "sample_fake.mp4")
    assert r.verdict == "invalid", r.reasons
    assert r.checks["container_parse"] is False


@pytest.mark.asyncio
async def test_mkv_verified_with_null_stream_duration():
    """MKV 流级 duration 为 null，必须退化用容器时长，不得误判异常。"""
    r = await check_media(TS / "sample_with_sub.mkv")
    assert r.verdict == "verified", r.reasons
    assert r.checks.get("duration_degraded") is True
    assert r.checks["duration_anomaly"] is False


@pytest.mark.asyncio
async def test_no_audio_asr_not_verified():
    """无音轨 + purpose=asr → 至少降为 likely（不能是 verified）。"""
    r = await check_media(TS / "sample_no_audio.mp4", purpose="asr")
    assert r.verdict in ("likely", "partial"), r.verdict
    assert r.verdict != "verified"
    assert any("无音轨" in x for x in r.reasons)


@pytest.mark.asyncio
async def test_no_audio_playback_ok():
    """同一无音轨文件用于 playback 时应为 verified（可正常播放）。"""
    r = await check_media(TS / "sample_no_audio.mp4", purpose="playback")
    assert r.verdict == "verified", r.reasons


# ----------------------------- check_cues -----------------------------
def test_cues_ok():
    cues = [
        {"start_ms": 0, "end_ms": 1000},
        {"start_ms": 1000, "end_ms": 40000},
    ]
    res = check_cues(cues, duration_ms=45000)
    assert res["ok"] is True, res["reasons"]
    assert res["max_end_ms"] == 40000
    assert res["coverage_ratio"] > 0.5


def test_cues_overflow():
    """末条结束超出 时长+容差 → ok=False。"""
    cues = [{"start_ms": 0, "end_ms": 300000}]
    res = check_cues(cues, duration_ms=100000)
    assert res["ok"] is False
    assert any("超出" in x for x in res["reasons"])


def test_cues_low_coverage():
    """时间戳合法但只覆盖很短的片段 → 低覆盖，ok=False。"""
    cues = [
        {"start_ms": 1000, "end_ms": 2000},
        {"start_ms": 2000, "end_ms": 3000},
    ]
    res = check_cues(cues, duration_ms=100000)
    assert res["ok"] is False
    assert any("覆盖率" in x for x in res["reasons"])


def test_cues_empty():
    res = check_cues([], duration_ms=10000)
    assert res["ok"] is False
    assert res["reasons"]
    assert res["coverage_ratio"] == 0.0


def test_cues_overlap():
    """时间戳重叠（超过 1ms 容差）→ ok=False。"""
    cues = [
        {"start_ms": 0, "end_ms": 5000},
        {"start_ms": 4000, "end_ms": 10000},
    ]
    res = check_cues(cues, duration_ms=20000)
    assert res["ok"] is False
    assert any("重叠" in x for x in res["reasons"])

