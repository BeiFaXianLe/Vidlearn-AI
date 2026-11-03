"""时间轴对齐（L5，轻量版）：用 FFmpeg 静音检测把字幕边界吸附到语音起止。

不依赖 torch，CPU 秒级完成。适用：字幕整体偏早/偏晚、段内切分不准。
（若需对“任意文本 + 音频”做强对齐，可另行接入 stable-ts/whisperx，见 align_available().）
"""
from __future__ import annotations

import re
from pathlib import Path

_SIL_START = re.compile(r"silence_start:\s*([0-9.]+)")
_SIL_END = re.compile(r"silence_end:\s*([0-9.]+)")


async def detect_silences(ffmpeg: str, media_path: Path, *, noise_db: int = -32,
                          min_silence: float = 0.25, run_cmd=None) -> list[tuple[int, int]]:
    """返回静音区间列表 [(start_ms, end_ms)]。"""
    if run_cmd is None:
        from apps.adapters._util import run_cmd  # 复用现有子进程封装
    args = [ffmpeg, "-hide_banner", "-nostats", "-i", str(media_path),
            "-vn", "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
            "-f", "null", "-"]
    rc, out, err = await run_cmd(args, timeout=300)
    text = (err or "") + (out or "")
    starts = [float(x) for x in _SIL_START.findall(text)]
    ends = [float(x) for x in _SIL_END.findall(text)]
    res = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else None
        if e is not None and e > s:
            res.append((int(s * 1000), int(e * 1000)))
    return res


def snap_cues(cues: list[dict], silences: list[tuple[int, int]],
              *, tolerance_ms: int = 700) -> tuple[list[dict], list[dict]]:
    """把 cue 的起止吸附到相邻静音区间边界。返回 (新 cues, 变更列表)。"""
    if not silences or not cues:
        return cues, []

    def inside_silence(t: int) -> tuple[int, int] | None:
        for s, e in silences:
            if s <= t <= e:
                return (s, e)
        return None

    out = []
    changes = []
    n = len(cues)
    for i, c in enumerate(cues):
        start = int(c["start_ms"])
        end = int(c["end_ms"])
        ns, ne = start, end

        # 起点落在静音里，或紧邻其后的语音起点 → 吸到静音结束（语音开始）
        si = inside_silence(start)
        if si and abs(start - si[1]) <= tolerance_ms * 2:
            ns = si[1]
        # 终点落在静音里 → 吸到静音开始（语音结束）
        ei = inside_silence(end)
        if ei and abs(end - ei[0]) <= tolerance_ms * 2:
            ne = ei[0]

        # 边界约束：保证单调、不重叠、不越界
        if i > 0:
            ns = max(ns, out[-1]["end_ms"] + 1)
        if i < n - 1:
            ne = min(ne, int(cues[i + 1]["start_ms"]) - 1)
        if ne - ns < 200:                     # 吸附后太短，放弃该段
            ns, ne = start, end
        if (ns, ne) != (start, end):
            nc = dict(c)
            nc["start_ms"], nc["end_ms"] = ns, ne
            out.append(nc)
            changes.append({"segment_index": i, "start_ms": start,
                            "before": c.get("text", ""), "after": c.get("text", ""),
                            "reason": "align", "confidence": 0.7,
                            "time_from": [start, end], "time_to": [ns, ne]})
        else:
            out.append(dict(c))
    # 修复可能的静音吸附造成的重叠
    for i in range(1, len(out)):
        if out[i]["start_ms"] < out[i - 1]["end_ms"]:
            out[i]["start_ms"] = out[i - 1]["end_ms"] + 1
            if out[i]["end_ms"] <= out[i]["start_ms"]:
                out[i]["end_ms"] = out[i]["start_ms"] + 300
    return out, changes



def _speech_intervals(silences: list[tuple[int, int]], total_ms: int) -> list[tuple[int, int]]:
    """把静音区间补集转成语音区间。"""
    speech = []
    cur = 0
    for s, e in sorted(silences):
        if s > cur:
            speech.append((cur, s))
        cur = max(cur, e)
    if cur < total_ms:
        speech.append((cur, total_ms))
    return speech


def estimate_offset(cues: list[dict], silences: list[tuple[int, int]],
                    total_ms: int | None = None) -> int:
    """估计字幕整体偏移（毫秒）：cue 起点相对最近语音起点的中位差。

    正数=字幕偏晚，负数=字幕偏早。用于判断是否需要整体平移。
    """
    if not cues or not silences:
        return 0
    total = total_ms or int(max(c.get("end_ms", 0) for c in cues)) + 1000
    speech = _speech_intervals(silences, total)
    if not speech:
        return 0
    starts = [s for s, _ in speech]
    import bisect
    deltas = []
    for cue in cues:
        t = int(cue["start_ms"])
        i = bisect.bisect_left(starts, t)
        cand = []
        if i < len(starts):
            cand.append(starts[i] - t)
        if i > 0:
            cand.append(starts[i - 1] - t)
        if cand:
            deltas.append(min(cand, key=abs))
    if not deltas:
        return 0
    deltas.sort()
    return int(deltas[len(deltas) // 2])


def align_cues(cues: list[dict], silences: list[tuple[int, int]], *,
               min_offset_ms: int = 350, tolerance_ms: int = 600) -> tuple[list[dict], list[dict]]:
    """只在检测到「明显整体偏移」时做校正（更保守，避免破坏已对齐的 ASR 字幕）。

    - |全局偏移| < min_offset_ms → 视为已对齐，原样返回（无改动）
    - 否则整体平移该偏移量，并做边界约束（>=0、单调、不重叠）
    """
    if not cues or not silences:
        return cues, []
    total = int(max(c.get("end_ms", 0) for c in cues)) + 2000
    off = estimate_offset(cues, silences, total)
    if abs(off) < min_offset_ms:
        return cues, []

    out, changes = [], []
    prev_end = -1
    for i, c in enumerate(cues):
        ns = max(0, int(c["start_ms"]) + off)
        ne = max(ns + 100, int(c["end_ms"]) + off)
        if ns <= prev_end:            # 防重叠
            ns = prev_end + 1
            ne = max(ne, ns + 100)
        nc = dict(c)
        nc["start_ms"], nc["end_ms"] = ns, ne
        out.append(nc)
        changes.append({"segment_index": i, "start_ms": int(c["start_ms"]),
                        "before": c.get("text", ""), "after": c.get("text", ""),
                        "reason": "align", "confidence": 0.65,
                        "time_from": [int(c["start_ms"]), int(c["end_ms"])],
                        "time_to": [ns, ne]})
        prev_end = ne
    return out, changes


def align_available() -> bool:
    try:
        import stable_whisper  # noqa: F401
        return True
    except Exception:
        return False
