"""繁简转换与字幕分段合并测试。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.core.textnorm import merge_cues, simplify_cues, strip_time_tags, to_simplified


# ---------------- 繁简转换 ----------------
def test_to_simplified_converts_traditional():
    assert to_simplified("歡迎收看") == "欢迎收看"
    assert to_simplified("日本便利店巨頭") == "日本便利店巨头"
    assert to_simplified("關於臺灣") == "关于台湾"


def test_to_simplified_keeps_simplified_unchanged():
    assert to_simplified("这个视频讲的是Redis持久化机制") == "这个视频讲的是Redis持久化机制"


def test_to_simplified_empty():
    assert to_simplified("") == ""


def test_simplify_cues_keeps_timestamps():
    cues = [{"start_ms": 0, "end_ms": 100, "text": "時間消息"}]
    out = simplify_cues(cues)
    assert out[0]["text"] == "时间消息"
    assert out[0]["start_ms"] == 0 and out[0]["end_ms"] == 100


def test_strip_time_tags():
    assert strip_time_tags("<00:00:01.000>你好") == "你好"
    assert strip_time_tags("没有标签") == "没有标签"


# ---------------- 分段合并 ----------------
def _c(i, text, gap=100):
    start = i * 1000
    return {"start_ms": start, "end_ms": start + 500, "text": text}


def test_merge_short_sentences_into_paragraph():
    cues = [_c(0, "第一句"), _c(1, "第二句"), _c(2, "第三句")]
    out = merge_cues(cues)
    assert len(out) == 1
    assert out[0]["text"] == "第一句第二句第三句"
    assert out[0]["start_ms"] == 0
    assert out[0]["end_ms"] == 2500


def test_merge_splits_on_sentence_end():
    cues = [_c(0, "第一句话。"), _c(1, "第二句话。")]
    out = merge_cues(cues)
    assert len(out) == 2


def test_merge_splits_on_large_gap():
    cues = [_c(0, "第一句"), {"start_ms": 5000, "end_ms": 5500, "text": "第二句"}]
    out = merge_cues(cues)
    assert len(out) == 2


def test_merge_respects_max_chars():
    cues = [_c(0, "a" * 40), _c(1, "b" * 40)]
    out = merge_cues(cues, max_chars=50)
    assert len(out) == 2


def test_merge_respects_max_duration():
    cues = [_c(0, "a"), _c(1, "b")]
    out = merge_cues(cues, max_duration_ms=500)
    assert len(out) == 2


def test_merge_keeps_comma_join_without_space():
    cues = [_c(0, "前半句，"), _c(1, "后半句")]
    out = merge_cues(cues)
    assert len(out) == 1
    assert out[0]["text"] == "前半句，后半句"


def test_merge_sorts_unordered_input():
    cues = [_c(2, "第三句"), _c(0, "第一句"), _c(1, "第二句")]
    out = merge_cues(cues)
    assert out[0]["text"].startswith("第一句")


def test_merge_empty():
    assert merge_cues([]) == []


def test_merge_drops_empty_text():
    # 间隔很小（<700ms），应合并为一段；空白句应被丢弃
    cues = [{"start_ms": 0, "end_ms": 500, "text": "有效"},
            {"start_ms": 550, "end_ms": 1000, "text": "   "},
            {"start_ms": 1050, "end_ms": 1600, "text": "也有"}]
    out = merge_cues(cues)
    assert len(out) == 1
    assert out[0]["text"] == "有效也有"
