"""字幕质量评分（L0）：定位问题段落，指导是否/在哪校准。"""
from __future__ import annotations

import difflib

# 阈值
MAX_CHARS_PER_SEC = 8.0
MIN_CHARS_PER_SEC = 0.3
MIN_CUE_MS = 250
MAX_CUE_MS = 15000


def score_cues(cues: list[dict], *, duration_ms: int | None = None,
               glossary_variants: list[str] | None = None) -> dict:
    """返回 {score, issues, stats}。score 0-100（越高越好）。"""
    variants = [v for v in (glossary_variants or []) if v]
    issues: list[dict] = []
    stats = {
        "count": len(cues),
        "total_ms": 0,
        "overlaps": 0,
        "non_monotonic": 0,
        "empty": 0,
        "too_fast": 0,
        "too_short": 0,
        "too_long": 0,
        "duplicates": 0,
        "variant_hits": 0,
        "coverage": 0.0,
    }
    if not cues:
        return {"score": 0.0, "issues": [], "stats": stats, "detail": "无字幕"}

    total = 0
    prev_end = -1
    prev_text = None
    for i, c in enumerate(cues):
        start = int(c.get("start_ms", 0))
        end = int(c.get("end_ms", 0))
        text = (c.get("text") or "").strip()
        dur = max(1, end - start)
        total += dur
        reasons = []
        if end <= start:
            reasons.append("时间非法")
            stats["non_monotonic"] += 1
        if start < prev_end:
            stats["overlaps"] += 1
            reasons.append("与上段重叠")
        if not text:
            stats["empty"] += 1
            reasons.append("空字幕")
        cs = len(text) / (dur / 1000.0)
        if text and cs > MAX_CHARS_PER_SEC:
            stats["too_fast"] += 1
            reasons.append(f"语速异常({cs:.1f}字/秒)")
        if dur < MIN_CUE_MS:
            stats["too_short"] += 1
            reasons.append("时长过短")
        if dur > MAX_CUE_MS:
            stats["too_long"] += 1
            reasons.append("时长过长")
        if text and text == prev_text:
            stats["duplicates"] += 1
            reasons.append("与上段重复")
        hit_variants = [v for v in variants if v in text]
        if hit_variants:
            stats["variant_hits"] += 1
            reasons.append("含已知错误写法:" + "/".join(hit_variants[:3]))
        if reasons:
            issues.append({"index": i, "start_ms": start, "text": text, "reasons": reasons})
        prev_end = max(prev_end, end)
        prev_text = text

    stats["total_ms"] = total
    if duration_ms and duration_ms > 0:
        stats["coverage"] = round(min(1.0, total / duration_ms), 3)

    # 扣分
    n = len(cues)
    penalty = 0.0
    penalty += stats["overlaps"] / n * 40
    penalty += stats["non_monotonic"] / n * 30
    penalty += stats["empty"] / n * 40
    penalty += stats["duplicates"] / n * 20
    penalty += stats["too_fast"] / n * 15
    penalty += stats["too_short"] / n * 8
    penalty += stats["too_long"] / n * 8
    penalty += min(30, stats["variant_hits"] * 3)
    if duration_ms and stats["coverage"] < 0.6:
        penalty += (0.6 - stats["coverage"]) * 50
    score = max(0.0, min(100.0, 100.0 - penalty))
    return {"score": round(score, 1), "issues": issues, "stats": stats}


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()
