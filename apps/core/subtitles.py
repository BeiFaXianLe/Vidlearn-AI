"""S3-04/05 内嵌字幕提取与用户字幕导入；S3-06/07 平台字幕标准化与 Transcript 分段模型。

- 纯标准库实现 SRT / WebVTT / ASS(SSA) 解析，不引入 pysrt 等第三方依赖。
- 统一 cues 结构：[{"start_ms": int, "end_ms": int, "text": str}]。
- 内嵌字幕用 ffprobe 枚举（-select_streams s）、ffmpeg -map 0:s:<i> 导出为 srt。
- 子进程一律用参数数组（参考 apps/adapters/_util.py），绝不拼 shell。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from apps.adapters._util import run_cmd

# ---------------------------------------------------------------------------
# 通用文本预处理
# ---------------------------------------------------------------------------

_BOM = "\ufeff"


def _read_text(path: Path) -> str:
    """读字幕文件：宽容处理 BOM，优先 utf-8，回退 utf-8-sig / gb18030。"""
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def _clean_lines(text: str) -> list[str]:
    """去 BOM、统一换行（CRLF/CR → LF）、按行拆分。"""
    if text.startswith(_BOM):
        text = text[len(_BOM):]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.split("\n")


# ---------------------------------------------------------------------------
# 时间戳解析
# ---------------------------------------------------------------------------

# SRT / VTT: [HH:]MM:SS<sep>mmm  (分割符 , 或 .)
_TS_RE = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[,.](\d{1,3}))?"
)


def _ts_to_ms(ts: str) -> int | None:
    """把 `HH:MM:SS,mmm` / `MM:SS.mmm` / `SS.mmm` 转毫秒。"""
    m = _TS_RE.search(ts.strip())
    if not m:
        return None
    h = int(m.group(1) or 0)
    mm = int(m.group(2) or 0)
    ss = int(m.group(3) or 0)
    frac = m.group(4) or "0"
    ms = int((frac + "000")[:3])  # 右侧补零到 3 位
    return ((h * 60 + mm) * 60 + ss) * 1000 + ms


def _ass_ts_to_ms(ts: str) -> int | None:
    """ASS/SSA 时间 `H:MM:SS.cc`（厘秒，两位小数）→ 毫秒。"""
    m = re.match(r"\s*(\d+):(\d{1,2}):(\d{1,2})(?:[.,](\d{1,3}))?\s*", ts)
    if not m:
        return None
    h, mm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3))
    frac = m.group(4) or "0"
    # ASS 通常两位（厘秒），按位数换算：2 位→×10，3 位→原值
    if len(frac) == 1:
        ms = int(frac) * 100
    elif len(frac) == 2:
        ms = int(frac) * 10
    else:
        ms = int(frac[:3])
    return ((h * 60 + mm) * 60 + ss) * 1000 + ms


# SRT / VTT 时间行：start --> end [settings]
_ARROW_RE = re.compile(r"^\s*(\S+)\s*-->\s*(\S+)")


def _mk_cue(start_ms: int, end_ms: int, text: str) -> dict:
    return {"start_ms": int(start_ms), "end_ms": int(end_ms), "text": text.strip()}


# ---------------------------------------------------------------------------
# SRT
# ---------------------------------------------------------------------------

def parse_srt(text: str) -> list[dict]:
    """解析 SubRip。返回 [{"start_ms", "end_ms", "text"}]（未 normalize）。

    容错：BOM、CRLF、序号缺失、多行文本、`,` 或 `.` 毫秒分割。
    """
    lines = _clean_lines(text)
    cues: list[dict] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        # 若当前行不是时间行，可能是序号行，往下找时间行
        m = _ARROW_RE.match(line)
        if not m:
            if i + 1 < n and _ARROW_RE.match(lines[i + 1]):
                i += 1
                m = _ARROW_RE.match(lines[i])
            else:
                i += 1
                continue
        start = _ts_to_ms(m.group(1))
        end = _ts_to_ms(m.group(2))
        i += 1
        # 收集文本直到空行或下一个时间/序号块
        buf: list[str] = []
        while i < n:
            l2 = lines[i]
            if not l2.strip():
                i += 1
                break
            if _ARROW_RE.match(l2):
                break
            # 序号行紧跟时间行的情况：整块序号 + 时间视为新 cue
            if (i + 1 < n and l2.strip().isdigit()
                    and _ARROW_RE.match(lines[i + 1])):
                break
            buf.append(l2)
            i += 1
        if start is None or end is None:
            continue
        cues.append(_mk_cue(start, end, "\n".join(buf)))
    return cues


# ---------------------------------------------------------------------------
# WebVTT
# ---------------------------------------------------------------------------

def parse_vtt(text: str) -> list[dict]:
    """解析 WebVTT。支持 `WEBVTT` 头、`00:00:01.500` 点号毫秒、cue 标识行、
    NOTE/STYLE/REGION 块与行尾 cue settings。
    """
    lines = _clean_lines(text)
    cues: list[dict] = []
    i, n = 0, len(lines)

    # 跳过 WEBVTT 头（可能带描述行），直到第一个空行
    if n and lines[0].lstrip(_BOM).strip().startswith("WEBVTT"):
        i = 1
        while i < n and lines[i].strip():
            i += 1

    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        # NOTE / STYLE / REGION 块：跳过整块直到空行
        head = line.strip().upper()
        if head.startswith(("NOTE", "STYLE", "REGION")):
            while i < n and lines[i].strip():
                i += 1
            continue
        m = _ARROW_RE.match(line)
        if not m:
            # 可能是 cue 标识行（identifier），下一行是时间行
            if i + 1 < n and _ARROW_RE.match(lines[i + 1]):
                i += 1
                m = _ARROW_RE.match(lines[i])
            else:
                i += 1
                continue
        start = _ts_to_ms(m.group(1))
        end = _ts_to_ms(m.group(2))
        i += 1
        buf: list[str] = []
        while i < n and lines[i].strip():
            if _ARROW_RE.match(lines[i]):
                break
            buf.append(lines[i])
            i += 1
        if start is None or end is None:
            continue
        cues.append(_mk_cue(start, end, "\n".join(buf)))
    return cues


# ---------------------------------------------------------------------------
# ASS / SSA
# ---------------------------------------------------------------------------

_ASS_DEFAULT_FORMAT = [
    "layer", "start", "end", "style", "name",
    "marginl", "marginr", "marginv", "effect", "text",
]


def parse_ass(text: str) -> list[dict]:
    """解析 ASS/SSA 的 `[Events]` 中 `Format:` / `Dialogue:`。

    时间格式 `0:00:01.50`（厘秒）。支持 SSA v4（`Marked=0`）与 ASS v4+（`Layer`）。
    Text 是最后一列，可能含逗号，按 Format 字段数切分并保留剩余为 text。
    """
    lines = _clean_lines(text)
    cues: list[dict] = []
    in_events = False
    fmt_cols: list[str] = list(_ASS_DEFAULT_FORMAT)
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            in_events = s.lower() == "[events]"
            continue
        if not in_events:
            continue
        low = s.lower()
        if low.startswith("format:"):
            cols = [c.strip().lower() for c in s.split(":", 1)[1].split(",")]
            if cols:
                fmt_cols = cols
            continue
        if not low.startswith("dialogue:"):
            continue
        payload = s.split(":", 1)[1]
        # text 字段包含逗号，最多按 len(fmt)-1 次切分
        maxsplit = max(0, len(fmt_cols) - 1)
        parts = payload.split(",", maxsplit)
        if len(parts) < len(fmt_cols):
            continue
        row = dict(zip(fmt_cols, parts))
        start = _ass_ts_to_ms(row.get("start", ""))
        end = _ass_ts_to_ms(row.get("end", ""))
        if start is None or end is None:
            continue
        raw_text = row.get("text", "")
        # 去掉内联样式覆盖块 {\\...}
        raw_text = re.sub(r"\{[^}]*\}", "", raw_text)
        # ASS 用 \N 表示硬换行
        raw_text = raw_text.replace("\\N", "\n").replace("\\n", "\n")
        cues.append(_mk_cue(start, end, raw_text))
    return cues


# ---------------------------------------------------------------------------
# 导出 SRT
# ---------------------------------------------------------------------------

def _ms_to_srt_ts(ms: int) -> str:
    if ms < 0:
        ms = 0
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(cues: list[dict]) -> str:
    """把标准化 cues 写回 SRT。毫秒 → `HH:MM:SS,mmm`。"""
    out: list[str] = []
    for i, c in enumerate(cues, start=1):
        out.append(str(i))
        out.append(f"{_ms_to_srt_ts(int(c['start_ms']))} --> {_ms_to_srt_ts(int(c['end_ms']))}")
        out.append(str(c.get("text", "")))
        out.append("")  # 块间空行
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 标准化
# ---------------------------------------------------------------------------

def normalize_cues(cues, *, min_gap_ms: int = 1) -> list[dict]:
    """排序 → 去空 → 修正 start<end → 合并重叠/相邻重复。

    - 空文本（含仅空白）剔除。
    - 起始/结束转为毫秒整数；start >= end 时修正（end = start + min_gap_ms）。
    - 时间完全重叠或 start 相邻的重复文本合并为一条（取并集区间）。
    """
    items: list[dict] = []
    for c in cues or []:
        text = (c.get("text") or "").strip()
        if not text:
            continue
        try:
            start = int(round(float(c.get("start_ms", 0))))
            end = int(round(float(c.get("end_ms", 0))))
        except (TypeError, ValueError):
            continue
        if end <= start:
            end = start + max(1, int(min_gap_ms))
        items.append({"start_ms": start, "end_ms": end, "text": text})

    items.sort(key=lambda x: (x["start_ms"], x["end_ms"]))

    merged: list[dict] = []
    for it in items:
        if not merged:
            merged.append(dict(it))
            continue
        prev = merged[-1]
        same_text = prev["text"] == it["text"]
        # 完全/区间重叠，或文本相同且相邻（间隔 <= min_gap_ms）
        overlap = it["start_ms"] < prev["end_ms"]
        adjacent_dup = same_text and it["start_ms"] - prev["end_ms"] <= max(0, int(min_gap_ms))
        if same_text and (overlap or adjacent_dup):
            prev["end_ms"] = max(prev["end_ms"], it["end_ms"])
            continue
        if overlap and it["start_ms"] <= prev["start_ms"]:
            # 非重复但被完全包含：跳过，保留较长的前一条
            if it["end_ms"] <= prev["end_ms"]:
                continue
        merged.append(dict(it))
    return merged


# ---------------------------------------------------------------------------
# 平台字幕 → 标准 cues（S3-06）
# ---------------------------------------------------------------------------

def cues_from_bilibili(chosen: dict) -> list[dict]:
    """把 bilibili.fetch_subtitles 返回的 chosen 转成标准 cues（做 normalize）。

    chosen 期望含 {"cues": [{"start_ms", "end_ms", "text"}]}；缺少返回 []。
    """
    if not chosen:
        return []
    raw = chosen.get("cues") or []
    return normalize_cues(raw)


# ---------------------------------------------------------------------------
# 内嵌字幕提取（S3-04/05）
# ---------------------------------------------------------------------------

async def _ffprobe_subtitle_streams(media_path: Path, ffprobe: str) -> list[dict]:
    rc, out, _ = await run_cmd([
        ffprobe, "-v", "error", "-print_format", "json",
        "-select_streams", "s", "-show_streams", str(media_path),
    ], timeout=60)
    if rc != 0 or not out.strip():
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    streams = [s for s in (data.get("streams") or [])
               if s.get("codec_type") == "subtitle"]
    # 按流在文件中的绝对 index 升序，保证 map 0:s:<i> 的 i 与序号一致
    streams.sort(key=lambda s: s.get("index", 0))
    return streams


async def extract_embedded_subtitles(
    media_path: Path, out_dir: Path, *, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
) -> list[dict]:
    """用 ffprobe 枚举字幕流，逐个用 ffmpeg 导出为 srt。无字幕流返回 []。

    返回 [{"index", "codec", "language", "path", "cues"}]。
    index 为字幕流在其字幕流序列中的序号（对应 -map 0:s:<index>）。
    """
    media_path = Path(media_path)
    out_dir = Path(out_dir)
    if not media_path.exists():
        return []
    streams = await _ffprobe_subtitle_streams(media_path, ffprobe)
    if not streams:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    for i, st in enumerate(streams):
        suffix = st.get("codec_name") or "sub"
        out_path = out_dir / f"sub_{i}_{suffix}.srt"
        rc, _, _ = await run_cmd([
            ffmpeg, "-v", "error", "-y",
            "-i", str(media_path),
            "-map", f"0:s:{i}",
            "-c:s", "srt",
            str(out_path),
        ], timeout=300)
        cues: list[dict] = []
        if rc == 0 and out_path.exists():
            cues = normalize_cues(parse_srt(_read_text(out_path)))
        tags = st.get("tags") or {}
        results.append({
            "index": i,
            "codec": st.get("codec_name"),
            "language": tags.get("language"),
            "path": str(out_path) if out_path.exists() else None,
            "cues": cues,
        })
    return results
