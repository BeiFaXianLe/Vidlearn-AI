"""中文拼音工具：同音/近音检测与纠错的基础。

设计要点：
- 只对连续中文（CJK）片段做匹配，避免误处理英文/数字
- **模糊拼音**：把常见 ASR 混淆对归一化（前后鼻音 in/ing、en/eng、an/ang，
  平翘舌 z/zh、c/ch、s/sh，n/l，f/h，ü/v），显著提升同音召回
- 替换需满足：等长 + 归一化拼音序列一致 + 与目标词不同
- 返回时区分「精确同音」(confidence 高) 与「模糊近音」(confidence 低，便于复核)
"""
from __future__ import annotations

import re

CJK = re.compile(r"[\u4e00-\u9fff]+")


def available() -> bool:
    try:
        import pypinyin  # noqa: F401
        return True
    except Exception:
        return False


def _raw_pinyin_list(text: str) -> list[str]:
    try:
        from pypinyin import Style, pinyin
    except Exception:
        return []
    return [p[0] for p in pinyin(text, style=Style.NORMAL, heteronym=False, errors="ignore")]


def canonical_syllable(s: str) -> str:
    """把音节归一到「ASR 混淆等价类」。"""
    s = s.lower()
    # 声母：平翘舌、n/l、f/h
    for a, b in (("zh", "z"), ("ch", "c"), ("sh", "s"), ("n", "l"), ("f", "h")):
        if s.startswith(a):
            s = b + s[len(a):]
            break
    # 韵母：v/ü → u
    s = s.replace("v", "u").replace("ü", "u")
    # 前后鼻音：去尾 g（ing/eng/ang），注意 ong 不动（ong 与 on 不混淆）
    if s.endswith("ing"):
        s = s[:-1]
    elif s.endswith("eng"):
        s = s[:-1]
    elif s.endswith("ang"):
        s = s[:-1]
    return s


def term_signature(term: str, fuzzy: bool = True) -> list[str] | None:
    """返回术语的逐字拼音序列（含非中文返回 None）。fuzzy=True 返回归一化序列。"""
    if not term or not CJK.fullmatch(term):
        return None
    py = _raw_pinyin_list(term)
    if len(py) != len(term):
        return None
    return [canonical_syllable(p) for p in py] if fuzzy else py


def find_homophones(text: str, term: str, sig: list[str] | None = None,
                    fuzzy: bool = True) -> list[tuple[int, int, bool]]:
    """查找与 term 同音/近音片段，返回 [(start, end, exact)]。"""
    if sig is None:
        sig = term_signature(term, fuzzy)
    if not sig:
        return []
    raw_sig = term_signature(term, fuzzy=False)
    hits: list[tuple[int, int, bool]] = []
    for m in CJK.finditer(text):
        run = m.group(0)
        base = m.start()
        L = len(term)
        if len(run) < L:
            continue
        raw = _raw_pinyin_list(run)
        if len(raw) != len(run):
            continue
        canon = [canonical_syllable(p) for p in raw]
        for i in range(len(run) - L + 1):
            seg = run[i:i + L]
            if seg == term:
                continue
            if fuzzy:
                if canon[i:i + L] != sig:
                    continue
                exact = (raw[i:i + L] == raw_sig)
            else:
                if raw[i:i + L] != sig:
                    continue
                exact = True
            hits.append((base + i, base + i + L, exact))
    return hits


def replace_homophones(text: str, term: str, sig: list[str] | None = None,
                       fuzzy: bool = True) -> tuple[str, list[dict]]:
    """替换为 term，返回 (新文本, [{'start','end','exact'}...])。"""
    hits = find_homophones(text, term, sig, fuzzy)
    if not hits:
        return text, []
    out, last, changed = [], 0, []
    for s, e, exact in hits:
        if s < last:
            continue
        out.append(text[last:s])
        out.append(term)
        changed.append({"start": s, "end": e, "exact": exact})
        last = e
    out.append(text[last:])
    return "".join(out), changed
