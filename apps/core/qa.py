"""视频问答（S5 增强）：基于字幕的 RAG-lite 问答，支持流式输出与时间点引用。

设计：
- 上下文：按段落合并后的字幕（带 mm:ss），超长时按关键词粗筛相关段落 + 首尾摘要
- 提示词要求回答中用【mm:ss】标注引用
- 流式返回，前端把【mm:ss】渲染为可点击跳转
"""
from __future__ import annotations

import re

SYSTEM = (
    "你是视频学习助手。只能依据用户提供的字幕内容回答，不得编造字幕中没有的信息。\n"
    "回答要求：\n"
    "1. 简洁准确，使用中文；必要时用要点列举\n"
    "2. 引用字幕依据时，用【mm:ss】标注对应时间点（必须是字幕中真实出现的时间）\n"
    "3. 若字幕中找不到答案，明确说明「视频里没有提到」，不要猜\n"
    "4. 不要输出与问题无关的内容"
)

_CITE = re.compile(r"(\d{1,3}):([0-5]\d)")


def fmt_ms(ms: int) -> str:
    s = max(0, int(ms)) // 1000
    return f"{s // 60}:{s % 60:02d}"


def build_qa_context(cues: list[dict], question: str, *, max_chars: int = 24000,
                     window: int = 2) -> str:
    """构建问答上下文。优先保留与问题关键词相关的段落，并补首尾。"""
    if not cues:
        return ""
    lines = [f"[{fmt_ms(c['start_ms'])}] {c['text']}" for c in cues]

    # 关键词粗筛（中文按 2-gram，英文/数字按词）
    q = question or ""
    tokens = set(re.findall(r"[A-Za-z0-9]{2,}", q))
    zh = re.sub(r"[^\u4e00-\u9fff]", "", q)
    tokens |= {zh[i:i + 2] for i in range(len(zh) - 1)}

    keep: set[int] = set()
    if tokens:
        for i, c in enumerate(cues):
            text = c.get("text", "")
            if any(t and t in text for t in tokens):
                for j in range(max(0, i - window), min(len(cues), i + window + 1)):
                    keep.add(j)
    # 首尾各若干段作为背景
    for j in list(range(0, min(4, len(cues)))) + list(range(max(0, len(cues) - 3), len(cues))):
        keep.add(j)

    if not keep:
        keep = set(range(len(cues)))

    selected, total = [], 0
    for i in sorted(keep):
        ln = lines[i]
        if total + len(ln) > max_chars:
            continue
        selected.append(ln)
        total += len(ln)
    return "\n".join(selected)


def build_user_prompt(video_title: str, context: str, question: str) -> str:
    return (f"视频标题：{video_title}\n\n"
            f"字幕（每行开头是时间点）：\n{context}\n\n"
            f"问题：{question}\n\n请依据上面的字幕回答，并在引用处用【mm:ss】标注时间点。")


def extract_citations(text: str) -> list[str]:
    return list(dict.fromkeys(f"{m.group(1).zfill(2)}:{m.group(2)}" for m in _CITE.finditer(text)))
