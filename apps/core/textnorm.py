"""文本规范化：繁简转换 + 字幕分段合并。

- `to_simplified`：繁体 → 简体（OpenCC t2s），在字幕入库前统一处理
- `merge_cues`：把逐句字幕合并成段落，用于「一段一段」展示
"""
from __future__ import annotations

import re

# ---------- 繁简转换 ----------

_converter = None
_converter_failed = False


def _get_converter():
    global _converter, _converter_failed
    if _converter is not None or _converter_failed:
        return _converter
    try:
        from opencc import OpenCC
        _converter = OpenCC("t2s")
    except Exception:      # 未安装 opencc 时降级：原样返回，不阻断流程
        _converter_failed = True
        _converter = None
    return _converter


def to_simplified(text: str) -> str:
    """繁体转简体。转换器不可用时原样返回。"""
    if not text:
        return text
    cc = _get_converter()
    if cc is None:
        return text
    try:
        return cc.convert(text)
    except Exception:
        return text


def simplify_cues(cues: list[dict]) -> list[dict]:
    """对字幕分段的文本做繁简转换（时间戳不变）。"""
    if not cues:
        return cues
    return [dict(c, text=to_simplified(c.get("text", ""))) for c in cues]


# ---------- 字幕分段合并 ----------

# 句末标点：这些句子自然分段，不与下一句合并
_SENTENCE_END = "。！？!?…；;"


def merge_cues(cues: list[dict], *, max_gap_ms: int = 700, max_chars: int = 70,
                max_duration_ms: int = 20000, split_on_sentence_end: bool = True) -> list[dict]:
    """把逐句字幕合并为段落。

    规则：
    - 间隔 <= max_gap_ms 且合并后长度/时长不超限 → 合并
    - 上一句以句末标点结尾 → 不再合并（自然段落边界）
    - 保留首句的 start_ms 与末句的 end_ms
    """
    if not cues:
        return []
    ordered = sorted(cues, key=lambda c: (c.get("start_ms", 0), c.get("end_ms", 0)))
    out: list[dict] = []
    cur: dict | None = None
    cur_text_len = 0

    def flush():
        nonlocal cur, cur_text_len
        if cur is not None:
            out.append(cur)
        cur = None
        cur_text_len = 0

    for c in ordered:
        text = (c.get("text") or "").strip()
        if not text:
            continue
        start, end = c.get("start_ms", 0), c.get("end_ms", 0)
        if cur is None:
            cur = {"start_ms": start, "end_ms": end, "text": text}
            cur_text_len = len(text)
            continue

        gap = start - cur["end_ms"]
        prev_text = cur["text"]
        would_len = cur_text_len + len(text)
        would_dur = end - cur["start_ms"]
        ends_sentence = prev_text and prev_text[-1] in _SENTENCE_END

        can_merge = (
            gap <= max_gap_ms
            and would_len <= max_chars
            and would_dur <= max_duration_ms
            and not (split_on_sentence_end and ends_sentence)
            and gap >= -500              # 允许轻微重叠
        )
        if can_merge:
            cur["text"] = prev_text + text
            cur["end_ms"] = end
            cur_text_len = would_len
        else:
            flush()
            cur = {"start_ms": start, "end_ms": end, "text": text}
            cur_text_len = len(text)
    flush()
    return out


def strip_time_tags(text: str) -> str:
    """去掉 <00:00:01> 之类的内嵌时间标签（部分 ASR 输出带）。"""
    return re.sub(r"<\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}>", "", text or "").strip()
