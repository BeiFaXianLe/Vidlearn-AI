"""字幕标点恢复（S5 增强）。

faster-whisper 输出的中文没有标点。这里用云端 LLM 为字幕补标点：
- **只加标点，不改字、不增删内容**
- 结果存为**派生字幕轨**（source_type=asr_punct），原始 ASR 轨保留（PRD §5.3 要求）

实现要点：
1. 分批发送（避免超长上下文），每批带行号，要求返回同长度的数组
2. 逐条校验：长度变化过大 → 丢弃该条（视为模型改写）
3. 失败不影响原始字幕
"""
from __future__ import annotations

import json

BATCH_LINES = 40
MAX_LEN_RATIO = 1.6      # 加标点后长度不应超过原文的 1.6 倍
MIN_LEN_RATIO = 0.6

SYSTEM = (
    "你是中文字幕标点校正助手。任务：给每行字幕文本补上合适的标点符号。\n"
    "严格规则：\n"
    "1. 只能添加标点符号（，。？！；：、…等）和必要空格\n"
    "2. 不得修改、增加、删除任何汉字或数字\n"
    "3. 不得合并或拆分行\n"
    "4. 保持原有顺序与行数\n"
    "输出严格 JSON：{\"lines\": [\"第一行加标点后的文本\", \"第二行...\", ...]}"
)


def build_batches(lines: list[str], size: int = BATCH_LINES):
    for i in range(0, len(lines), size):
        yield i, lines[i:i + size]


def _prompt_for(batch: list[str]) -> str:
    body = "\n".join(f"{i+1}. {t}" for i, t in enumerate(batch))
    return (f"共 {len(batch)} 行，请为每一行补标点：\n{body}\n\n"
            f'输出 JSON：{{"lines": [...]}}，数组长度必须等于 {len(batch)}')


def _valid(original: str, punct: str) -> bool:
    if not original:
        return False
    if not punct:
        return False
    lo, hi = len(original), len(original)
    if hi == 0:
        return False
    ratio = len(punct) / max(1, hi)
    if ratio > MAX_LEN_RATIO or ratio < MIN_LEN_RATIO:
        return False
    # 汉字/数字等实义字符数量必须一致（只允许标点变化）
    def core(s: str) -> str:
        return "".join(ch for ch in s if not ch.isspace() and ch not in "，。？！；：、…,.?!;:()（）《》“”‘’\"'-—~")
    return core(original) == core(punct)


async def restore_punctuation(cues: list[dict], llm) -> dict:
    """为字幕补标点。

    返回 {"cues": [...], "changed": n, "total": n, "failed": bool}
    """
    if not cues:
        return {"cues": [], "changed": 0, "total": 0, "failed": False}
    out = [dict(c) for c in cues]
    lines = [(c.get("text") or "").strip() for c in out]
    changed = 0
    failed = False

    for offset, batch in build_batches(lines):
        try:
            data = await llm.complete_json(SYSTEM, _prompt_for(batch), {
                "type": "object",
                "required": ["lines"],
                "properties": {"lines": {"type": "array"}},
            })
        except Exception:
            failed = True
            continue
        got = data.get("lines") or []
        if not isinstance(got, list) or len(got) != len(batch):
            failed = True
            continue
        for i, punct in enumerate(got):
            idx = offset + i
            if not isinstance(punct, str):
                continue
            p = punct.strip()
            if _valid(lines[idx], p):
                out[idx]["text"] = p
                changed += 1
    return {"cues": out, "changed": changed, "total": len(out), "failed": failed}
