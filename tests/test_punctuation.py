"""字幕标点恢复测试（使用假 LLM，不联网）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.core.punctuation import _prompt_for, _valid, build_batches, restore_punctuation


class FakeLLM:
    """按原文加句号，模拟模型行为；可模拟改字/长度异常。"""

    def __init__(self, mode="punctuate"):
        self.mode = mode
        self.calls = 0

    async def complete_json(self, system, user, schema):
        self.calls += 1
        import re
        # 解析 "N. 文本" 形式的行
        items = re.findall(r"^\d+\.\s(.*)$", user, re.M)
        lines = []
        for src in items:
            if self.mode == "punctuate":
                lines.append(src + "。")
            elif self.mode == "rewrite":       # 改字，应被校验拒绝
                lines.append("改写后的完全不同内容在这里出现")
            elif self.mode == "longtext":      # 过长，应被拒绝
                lines.append(src + "啊" * 200)
            elif self.mode == "wronglen":     # 行数不符，应整批丢弃
                lines = lines[:1]
            else:
                lines.append(src)
        return {"lines": lines}


def _cues(n=3):
    return [{"start_ms": i * 1000, "end_ms": i * 1000 + 900, "text": f"第{i}句内容"}
            for i in range(n)]


@pytest.mark.asyncio
async def test_restore_adds_punctuation():
    res = await restore_punctuation(_cues(3), FakeLLM())
    assert res["changed"] == 3
    assert res["cues"][0]["text"] == "第0句内容。"
    assert res["cues"][0]["start_ms"] == 0     # 时间戳不变


@pytest.mark.asyncio
async def test_restore_rejects_rewritten_text():
    res = await restore_punctuation(_cues(3), FakeLLM("rewrite"))
    assert res["changed"] == 0
    assert res["cues"][0]["text"] == "第0句内容"   # 原文保持


@pytest.mark.asyncio
async def test_restore_rejects_too_long():
    res = await restore_punctuation(_cues(3), FakeLLM("longtext"))
    assert res["changed"] == 0


@pytest.mark.asyncio
async def test_restore_handles_wrong_length():
    res = await restore_punctuation(_cues(3), FakeLLM("wronglen"))
    assert res["changed"] == 0
    assert res["failed"] is True


@pytest.mark.asyncio
async def test_restore_batches_long_input():
    llm = FakeLLM()
    res = await restore_punctuation(_cues(95), llm)
    assert llm.calls == 3          # 95 行 / 40 每批
    assert res["changed"] == 95
    assert res["cues"][94]["text"] == "第94句内容。"


def test_valid_allows_punctuation_only_change():
    assert _valid("你好世界", "你好，世界！") is True
    assert _valid("你好", "再见") is False
    assert _valid("你好", "") is False
    assert _valid("", "你好") is False


def test_batches_split():
    lines = [f"l{i}" for i in range(10)]
    batches = list(build_batches(lines, 4))
    assert [len(b[1]) for b in batches] == [4, 4, 2]
    assert batches[1][0] == 4


def test_prompt_includes_line_count():
    p = _prompt_for(["a", "b"])
    assert "共 2 行" in p
    assert "数组长度必须等于 2" in p


@pytest.mark.asyncio
async def test_restore_empty_cues():
    res = await restore_punctuation([], FakeLLM())
    assert res["cues"] == [] and res["total"] == 0
