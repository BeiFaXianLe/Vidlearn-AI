"""S4 本地 ASR 单元测试（不加载模型的部分）+ 可选真实转写。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pytest

from apps.core.asr import (
    ASROpts,
    _dedupe_boundary,
    _fix_overlaps,
    _validate,
    split_with_overlap,
)


def test_split_with_overlap_covers_and_overlaps():
    audio = np.zeros(16000 * 100, dtype=np.float32)  # 100s
    chunks = split_with_overlap(audio, 16000, segment_sec=30, overlap_sec=2)
    # 30, 58, 86 起点 → 至少 3 段，最后一段到 100s
    offsets = [round(o, 2) for _, o in chunks]
    assert offsets[0] == 0.0
    assert offsets[1] == 28.0
    # 最后一段覆盖到结尾
    last_chunk, last_off = chunks[-1]
    assert last_off + len(last_chunk) / 16000 >= 99.0


def test_split_short_audio_single_chunk():
    audio = np.zeros(16000 * 5, dtype=np.float32)
    chunks = split_with_overlap(audio, 16000, 30, 2)
    assert len(chunks) == 1


def test_dedupe_boundary_removes_repeated_tail():
    merged = [
        {"start_ms": 0, "end_ms": 3000, "text": "语音识别把字幕转写出来,"},
        {"start_ms": 3000, "end_ms": 6000, "text": "语音识别把字幕转写出来,最后再生成总结"},
    ]
    out = _dedupe_boundary(merged)
    assert len(out) == 2
    assert out[1]["text"] == "最后再生成总结"


def test_dedupe_boundary_drops_identical():
    merged = [
        {"start_ms": 0, "end_ms": 1000, "text": "同一句话"},
        {"start_ms": 1000, "end_ms": 2000, "text": "同一句话"},
    ]
    out = _dedupe_boundary(merged)
    assert len(out) == 1


def test_validate_detects_overlap_and_overflow():
    cues = [
        {"start_ms": 0, "end_ms": 5000, "text": "a"},
        {"start_ms": 4000, "end_ms": 6000, "text": "b"},      # 与上段重叠
        {"start_ms": 6000, "end_ms": 120000, "text": "c"},    # 越界（dur 100s）
    ]
    ok, issues = _validate(cues, duration_ms=100000)
    assert ok is False
    assert any("重叠" in i for i in issues)
    assert any("越界" in i for i in issues)


def test_validate_clean():
    cues = [{"start_ms": 0, "end_ms": 1000, "text": "a"},
            {"start_ms": 1000, "end_ms": 2000, "text": "b"}]
    ok, issues = _validate(cues, duration_ms=5000)
    assert ok is True and issues == []


def test_fix_overlaps_clips_and_drops():
    cues = [{"start_ms": 0, "end_ms": 5000, "text": "a"},
            {"start_ms": 4000, "end_ms": 6000, "text": "b"},   # 与上段重叠 → 裁到 5000
            {"start_ms": 4800, "end_ms": 4900, "text": "c"}]   # 完全落在上段内 → 丢弃
    out = _fix_overlaps(cues)
    assert len(out) == 2
    assert out[1]["start_ms"] == 5000
    ok, issues = _validate(out, duration_ms=10000)
    assert ok is True


@pytest.mark.asyncio
async def test_extract_audio_16k(tmp_path):
    from apps.core.asr import extract_audio_16k
    src = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "media" / "sample_no_sub.mp4"
    if not src.exists():
        pytest.skip("样本缺失")
    out = tmp_path / "a.wav"
    await extract_audio_16k(src, out)
    assert out.exists() and out.stat().st_size > 1000
    import wave
    with wave.open(str(out), "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1


@pytest.mark.asyncio
async def test_real_transcribe_tts(tmp_path):
    """真实转写（用已缓存模型；若无模型则跳过以免耗时）。"""
    import os
    from apps.core.asr import FasterWhisperASR
    src = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "media" / "tts_zh.wav"
    if not src.exists():
        pytest.skip("TTS 样本缺失")
    provider = FasterWhisperASR()
    res = await provider.transcribe(src, ASROpts(model="small", language="zh"))
    assert res.status in ("complete", "partial")
    assert len(res.cues) > 0
    assert res.cues[0]["start_ms"] >= 0

