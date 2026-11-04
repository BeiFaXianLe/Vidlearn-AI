"""AI 内容分析（S5）：摘要 / 章节 / 知识点 / 问答。

数据边界（PRD 冻结）：**只发送文本**（字幕/转写），绝不发送视频/音频/关键帧。
输出必须 JSON Schema 校验；时间戳只能来自字幕，不得由模型生成。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol

import httpx


class LLMError(Exception):
    pass


@dataclass
class LLMConfig:
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    timeout: int = 120
    max_input_chars: int = 60000


class LLMProvider(Protocol):
    async def complete_json(self, system: str, user: str, schema: dict) -> dict: ...


class OpenAICompatibleLLM:
    """OpenAI 兼容接口（DeepSeek/Qwen/OpenAI 均可用）。"""

    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg

    async def stream_text(self, system: str, user: str, *, temperature: float = 0.3):
        """流式返回文本增量（SSE），async generator 逐段 yield str。"""
        if not self.cfg.api_key:
            raise LLMError("未配置 LLM API Key")
        payload = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "stream": True,
        }
        headers = {"Authorization": f"Bearer {self.cfg.api_key}",
                   "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self.cfg.timeout) as client:
            async with client.stream("POST", f"{self.cfg.base_url.rstrip('/')}/chat/completions",
                                     json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", "ignore")
                    raise LLMError(f"LLM HTTP {resp.status_code}: {body[:200]}")
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        delta = obj["choices"][0].get("delta", {}).get("content")
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    if delta:
                        yield delta

    async def complete_json(self, system: str, user: str, schema: dict) -> dict:
        if not self.cfg.api_key:
            raise LLMError("未配置 LLM API Key")
        payload = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.cfg.api_key}",
                   "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self.cfg.timeout) as client:
            resp = await client.post(f"{self.cfg.base_url.rstrip('/')}/chat/completions",
                                     json=payload, headers=headers)
        if resp.status_code != 200:
            raise LLMError(f"LLM HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise LLMError(f"LLM 输出解析失败: {e}")
        _validate_schema(parsed, schema)
        return parsed


def _validate_schema(obj: dict, schema: dict) -> None:
    """轻量 JSON Schema 校验（required + type）。"""
    if not isinstance(obj, dict):
        raise LLMError("输出不是对象")
    for key in schema.get("required", []):
        if key not in obj:
            raise LLMError(f"缺少字段: {key}")
    for key, spec in (schema.get("properties") or {}).items():
        if key in obj and spec.get("type"):
            want = spec["type"]
            val = obj[key]
            ok = {
                "string": isinstance(val, str),
                "number": isinstance(val, (int, float)),
                "integer": isinstance(val, int),
                "array": isinstance(val, list),
                "object": isinstance(val, dict),
                "boolean": isinstance(val, bool),
            }.get(want, True)
            if not ok:
                raise LLMError(f"字段 {key} 类型应为 {want}")


# ---------------- Prompt & Schema ----------------

SUMMARY_SCHEMA = {
    "type": "object",
    "required": ["one_liner", "key_points", "content_scope"],
    "properties": {
        "one_liner": {"type": "string"},
        "key_points": {"type": "array"},
        "terms": {"type": "array"},
        "audience": {"type": "string"},
        "content_scope": {"type": "string"},
        # 仅当提供了用户职业档案时才会出现
        "career_advice": {"type": "string"},
    },
}

CHAPTERS_SCHEMA = {
    "type": "object",
    "required": ["chapters"],
    "properties": {"chapters": {"type": "array"}},
}

POINTS_SCHEMA = {
    "type": "object",
    "required": ["knowledge_points"],
    "properties": {"knowledge_points": {"type": "array"}},
}

SYSTEM_SUMMARY = (
    "你是视频内容分析助手。只依据用户提供的字幕文本作答，不得编造字幕中没有的内容。"
    "content_scope 只能是 full / partial / unknown。"
    "时间戳不得虚构；若文本未给时间，不要输出时间。输出严格 JSON。"
)

SYSTEM_SUMMARY_CAREER = (
    "你是视频内容分析助手，同时是一位务实、懂行的职业发展顾问。"
    "只依据用户提供的字幕文本作答，不得编造字幕中没有的内容。"
    "content_scope 只能是 full / partial / unknown。"
    "时间戳不得虚构；若文本未给时间，不要输出时间。"
    "额外要求：用户会提供自己的职业档案。请结合其职业与视频内容，在 career_advice 字段给出"
    "具体、可落地的职业发展建议。要求：用大白话，像同事聊天，不要堆术语、不要喊口号、"
    "不要说「提升核心竞争力」这类空话；要指出「这条视频里哪一点对你这个岗位有用、"
    "你可以怎么用、下一步可以做什么」。100~200 字，分 2~3 句写成一段话。"
    "如果视频内容与其职业关联很弱，就如实说明「关联不大」，并给一条最接近的启发，不要硬凑。"
    "输出严格 JSON。"
)

SYSTEM_CHAPTERS = (
    "你是视频章节划分助手。依据字幕文本划分章节。每个章节必须给出 start_ms、end_ms、title、"
    "summary，其中 start_ms/end_ms 必须来自字幕中真实出现的时间戳，不得虚构。输出严格 JSON。"
)

SYSTEM_POINTS = (
    "你是知识点提取助手。依据字幕文本提取知识点。每条含 title、content，"
    "可选 start_ms（必须来自字幕真实时间戳）。输出严格 JSON。"
)


def build_transcript_context(cues: list[dict], *, max_chars: int = 60000) -> str:
    """把分段拼成带时间戳的上下文（毫秒），超长截断并标注。"""
    lines = []
    total = 0
    for i, c in enumerate(cues):
        line = f"[{c['start_ms']}ms] {c['text']}"
        if total + len(line) > max_chars:
            lines.append("...(文本过长，已截断)")
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)


def normalize_timestamps(items: list[dict], valid_start_ms: set[int] | None,
                         cues: list[dict]) -> list[dict]:
    """把模型给的时间戳对齐到字幕里真实存在的时间戳；对不上的清空，防伪造。"""
    allowed = valid_start_ms if valid_start_ms is not None else {c["start_ms"] for c in cues}
    starts = sorted({c["start_ms"] for c in cues})

    def snap(ms) -> int | None:
        if not isinstance(ms, (int, float)):
            return None
        ms = int(ms)
        if ms in allowed:
            return ms
        # 找最近的真实字幕起点（容差 1500ms），否则视为伪造 → None
        if not starts:
            return None
        nearest = min(starts, key=lambda s: abs(s - ms))
        return nearest if abs(nearest - ms) <= 1500 else None

    for it in items:
        if "start_ms" in it:
            it["start_ms"] = snap(it.get("start_ms"))
        if "end_ms" in it:
            it["end_ms"] = snap(it.get("end_ms"))
    return items
