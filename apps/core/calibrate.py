"""字幕校准编排（L1 术语 → L2 拼音同音 → L3 LLM 约束 → L5 时间轴对齐）。

原则：**只改错字/标点/繁简，不改意思、不增删内容、不凭空改时间戳**；
所有改动写入变更日志，原始轨道永远保留，可回退。
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

from apps.core import subtitle_qc
from apps.core.pinyin_util import replace_homophones, term_signature

CALIBRATE_SYSTEM = (
    "你是专业的视频字幕校对员。任务：修正语音识别字幕里的**同音字、错别字、明显识别错误**，"
    "并可补齐句末标点。\n"
    "严格约束：\n"
    "1. 只做最小必要修改，不得改变原意、不得增删信息、不得润色改写\n"
    "2. 数字、英文、专有名词必须保持不变（除非明确属于下方术语表所列错误写法）\n"
    "3. 不得拆句/并句，不得改动时间\n"
    "4. 若某行无需修改，原样返回\n"
    "5. 只输出 JSON：{\"items\":[{\"i\":序号,\"text\":\"校对后的整行文字\"}]}"
)

CALIBRATE_SCHEMA = {
    "type": "object",
    "required": ["items"],
    "properties": {"items": {"type": "array"}},
}

_NUM = re.compile(r"\d+(?:\.\d+)?")


def _as_list(v) -> list[str]:
    """variants 可能来自 DB 的 JSON 字符串，统一转成字符串列表并做安全过滤。"""
    if v is None:
        return []
    if isinstance(v, str):
        try:
            v = __import__("json").loads(v)
        except Exception:
            v = [x for x in v.split(",") if x]
    if not isinstance(v, (list, tuple)):
        return []
    # 只接受长度>=2 的字符串，避免把单个字当错误写法造成大面积误替换
    return [str(x) for x in v if isinstance(x, str) and len(str(x)) >= 2]
_EN = re.compile(r"[A-Za-z][A-Za-z0-9+#.]*")


@dataclass
class CalibrationResult:
    cues: list[dict]
    changes: list[dict] = field(default_factory=list)
    qc_before: dict = field(default_factory=dict)
    qc_after: dict = field(default_factory=dict)
    llm_used: bool = False
    align_used: bool = False
    dropped_llm: int = 0


def _tokens(text: str) -> tuple[list[str], list[str]]:
    return _NUM.findall(text), [w.lower() for w in _EN.findall(text)]


def allowed_fix(before: str, after: str, term_set: set[str]) -> bool:
    """校验 LLM 的修改是否“安全”（仅错字/标点级）。"""
    b, a = before.strip(), after.strip()
    if not a or a == b:
        return False
    if not (0.6 <= len(a) / max(1, len(b)) <= 1.6):
        return False
    if difflib.SequenceMatcher(None, b, a).ratio() < 0.55:
        return False
    bn, be = _tokens(b)
    an, ae = _tokens(a)
    if sorted(bn) != sorted(an) or sorted(be) != sorted(ae):
        return False
    # 若删除了术语表以外的大段内容则拒绝
    return True


def _build_llm_prompt(lines: list[str], terms: list[dict]) -> str:
    gl = "、".join(t["term"] for t in terms[:60]) if terms else "（无）"
    body = "\n".join(f"{i}\t{t}" for i, t in enumerate(lines))
    return (f"术语表（正确写法，遇到同音错误请改成它）：{gl}\n\n"
            f"待校对字幕（每行：序号<TAB>文字）：\n{body}\n\n"
            f"请输出 JSON：{{\"items\":[{{\"i\":序号,\"text\":\"校对后整行\"}}]}}，只包含有改动的行。")


async def calibrate(
    cues: list[dict],
    *,
    terms: list[dict] | None = None,
    llm=None,
    media_path: Path | None = None,
    ffmpeg: str | None = None,
    duration_ms: int | None = None,
    do_pinyin: bool = True,
    do_llm: bool = True,
    do_align: bool = True,
    llm_batch: int = 30,
    progress=None,
) -> CalibrationResult:
    terms = terms or []
    variants_map: dict[str, str] = {}
    term_sigs: list[tuple[str, list[str]]] = []
    for t in terms:
        term = t.get("term", "")
        for v in _as_list(t.get("variants")):
            if v and v != term:
                variants_map[v] = term
        sig = term_signature(term)
        if sig:
            term_sigs.append((term, sig))
    variant_list = list(variants_map.keys())

    qc_before = subtitle_qc.score_cues(cues, duration_ms=duration_ms, glossary_variants=variant_list)
    working = [dict(c) for c in cues]
    changes: list[dict] = []
    result = CalibrationResult(cues=working, qc_before=qc_before)

    # ---------- L1/L2 术语 + 拼音同音 ----------
    if do_pinyin:
        for i, c in enumerate(working):
            text = c.get("text") or ""
            new = text
            reasons = []
            # 长词优先，避免「金州科技」被先按「金州」替换成「镜舟科技科技」
            for v in sorted(variants_map, key=len, reverse=True):
                term = variants_map[v]
                if v in new:
                    new2 = new.replace(v, term)
                    if new2 != new:
                        new = new2
                        reasons.append("variant")
            conf = 0.8
            for term, sig in term_sigs:
                new2, hits = replace_homophones(new, term, sig)
                if new2 != new:
                    new = new2
                    reasons.append("pinyin")
                    if hits and not all(h.get("exact") for h in hits):
                        conf = min(conf, 0.6)
            if new != text:
                c["text"] = new
                changes.append({"segment_index": i, "start_ms": c.get("start_ms"),
                                "before": text, "after": new,
                                "reason": "+".join(dict.fromkeys(reasons)) or "pinyin",
                                "confidence": conf})
        if progress:
            progress("术语与同音纠错", 25)

    # ---------- L3 LLM 约束校准 ----------
    if do_llm and llm is not None:
        term_set = {t["term"] for t in terms}
        n = len(working)
        done = 0
        for s in range(0, n, llm_batch):
            batch_idx = list(range(s, min(s + llm_batch, n)))
            lines = [(working[i].get("text") or "") for i in batch_idx]
            if not any(x.strip() for x in lines):
                continue
            try:
                data = await llm.complete_json(CALIBRATE_SYSTEM,
                                               _build_llm_prompt(lines, terms),
                                               CALIBRATE_SCHEMA)
            except Exception:
                result.dropped_llm += len(batch_idx)
                data = None
            if data:
                for item in (data.get("items") or []):
                    try:
                        k = int(item["i"])
                        new_text = str(item["text"]).strip()
                    except (KeyError, TypeError, ValueError):
                        continue
                    if not (0 <= k < len(batch_idx)):
                        continue
                    gi = batch_idx[k]
                    before = working[gi].get("text") or ""
                    if allowed_fix(before, new_text, term_set):
                        working[gi]["text"] = new_text
                        changes.append({"segment_index": gi, "start_ms": working[gi].get("start_ms"),
                                        "before": before, "after": new_text,
                                        "reason": "llm", "confidence": 0.75})
                    elif new_text and new_text != before:
                        result.dropped_llm += 1
            done += len(batch_idx)
            if progress:
                progress("LLM 校准", 25 + int(45 * done / max(1, n)))
        result.llm_used = True

    # ---------- L5 时间轴对齐 ----------
    if do_align and media_path and ffmpeg and Path(media_path).exists():
        try:
            from apps.core.align import align_cues, detect_silences
            sil = await detect_silences(ffmpeg, Path(media_path))
            qc_pre = subtitle_qc.score_cues(working, duration_ms=duration_ms,
                                            glossary_variants=variant_list)
            working2, align_changes = align_cues(working, sil)
            if align_changes:
                qc_post = subtitle_qc.score_cues(working2, duration_ms=duration_ms,
                                                 glossary_variants=variant_list)
                # 保险：对齐必须不降低质量，否则放弃（保护已对齐的 ASR 字幕）
                if qc_post["score"] >= qc_pre["score"] - 0.5:
                    working = working2
                    changes.extend(align_changes)
                    result.align_used = True
        except Exception:
            pass
        if progress:
            progress("时间轴对齐", 75)

    if progress:
        progress("评分", 90)
    result.cues = working
    result.changes = changes
    result.qc_after = subtitle_qc.score_cues(working, duration_ms=duration_ms,
                                             glossary_variants=variant_list)
    return result
