"""S3-02/03 媒体探测与多指标完整性判定 + S3-08 字幕覆盖率/完整性（S3-02/03/08）。

设计依据 docs/evidence/S0-04_05_ASR与完整性PoC结果.md：

多指标（全部实测，不依赖单一信号）：
  a) 容器可解析（ffprobe -print_format json 成功且有实际内容）
  b) 容器时长 vs 视频流时长差值（>2% 或 >1s 记异常；MKV 流级 duration 常为 null
     → 必须退化用容器时长，不能当异常）
  c) 完整解码 `ffmpeg -v error -i <path> -f null -` 退出码
  d) 尾部 2 秒解码（验证可解到结尾）
  e) 音视频流存在性；purpose="asr" 时无音轨 → 至少降为 "likely" 并记录原因

判定规则：
  无法解析容器 / 无声画流         → invalid
  完整解码失败：有视频 → partial，无视频 → invalid
  尾部解码失败                     → partial
  时长差异常                       → 至多 partial
  无音轨且 purpose="asr"          → likely
  否则                             → verified

子进程统一走 apps.adapters._util.run_cmd（参数数组，禁止 shell=True），不引入新依赖。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from apps.adapters._util import run_cmd

# verdict 严重度排序（越小越严重），用于“至多/至少”降级运算
_ORDER = ["invalid", "partial", "likely", "unknown", "verified"]
_RANK = {v: i for i, v in enumerate(_ORDER)}


def _worse(a: str, b: str) -> str:
    """返回更差的 verdict（rank 更小者更差）。"""
    return a if _RANK[a] <= _RANK[b] else b


def _clamp_max(v: str, cap: str) -> str:
    """把 v 限制在“至多 cap”的严重度（即不能好于 cap）。"""
    return v if _RANK[v] <= _RANK[cap] else cap


@dataclass
class IntegrityReport:
    verdict: str
    checks: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


def _to_ms(value) -> int | None:
    """把 ffprobe 的秒数字符串/数字转毫秒；无效返回 None。"""
    if value is None:
        return None
    try:
        return int(round(float(value) * 1000))
    except (TypeError, ValueError):
        return None


async def check_media(
    path: Path,
    *,
    ffprobe: str = "ffprobe",
    ffmpeg: str = "ffmpeg",
    purpose: str = "playback",
) -> IntegrityReport:
    """对媒体文件做多指标完整性判定，返回 IntegrityReport。"""
    path = Path(path)
    checks: dict = {}
    reasons: list[str] = []

    # ---- a) 容器可解析 ----
    rc, out, err = await run_cmd([
        ffprobe, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ], timeout=60)

    info: dict | None = None
    if rc == 0 and out.strip():
        try:
            info = json.loads(out)
        except json.JSONDecodeError:
            info = None
    if not info or not info.get("streams"):
        checks["container_parse"] = False
        checks["probe_error"] = (err.strip().splitlines()[-1] if err.strip() else "unparseable")
        reasons.append("容器无法解析")
        return IntegrityReport("invalid", checks, reasons)
    checks["container_parse"] = True

    streams = info.get("streams", [])
    fmt = info.get("format", {})

    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    has_video = len(video_streams) > 0
    has_audio = len(audio_streams) > 0

    # 可解码音轨：有音频流且 codec_name 非空（防止占位/损坏轨）
    decodable_audio = any(s.get("codec_name") for s in audio_streams)
    checks["has_video"] = has_video
    checks["has_audio"] = has_audio
    checks["decodable_audio"] = decodable_audio

    # 无声画流 → invalid
    if not has_video and not has_audio:
        reasons.append("无音视频流")
        return IntegrityReport("invalid", checks, reasons)

    # ---- b) 容器时长 vs 视频流时长 ----
    container_ms = _to_ms(fmt.get("duration"))
    checks["container_duration_ms"] = container_ms

    video_ms: int | None = None
    if video_streams:
        video_ms = _to_ms(video_streams[0].get("duration"))
    checks["video_stream_duration_ms"] = video_ms

    duration_anomaly = False
    if container_ms is not None and video_ms is not None:
        diff = abs(container_ms - video_ms)
        # >2% 或 >1s 记异常
        if diff > max(1000, int(container_ms * 0.02)):
            duration_anomaly = True
            reasons.append(
                f"容器时长与视频流时长差异 {diff}ms（容器 {container_ms} / 视频 {video_ms}）")
    else:
        # MKV 流级 duration 常为 null → 退化用容器时长，不作异常（PoC 2.3-1）
        checks["duration_degraded"] = True

    checks["duration_anomaly"] = duration_anomaly

    # 用于尾部解码的有效时长（优先容器时长）
    eff_ms = container_ms if container_ms is not None else video_ms

    # ---- c) 完整解码 ----
    rc_full, _, err_full = await run_cmd([
        ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-",
    ], timeout=900)
    full_ok = rc_full == 0 and not err_full.strip()
    checks["full_decode"] = full_ok
    if not full_ok:
        tail = (err_full.strip().splitlines() or ["unknown"])[-1]
        checks["full_decode_error"] = tail
        reasons.append(f"完整解码失败: {tail}")

    # ---- d) 尾部 2 秒解码 ----
    tail_ok = True
    if eff_ms and eff_ms > 0:
        ss_ms = max(0, eff_ms - 2000)
        rc_tail, _, err_tail = await run_cmd([
            ffmpeg, "-v", "error", "-ss", f"{ss_ms / 1000:.3f}",
            "-t", "2", "-i", str(path), "-f", "null", "-",
        ], timeout=120)
        tail_ok = rc_tail == 0 and not err_tail.strip()
        checks["tail_decode"] = tail_ok
        checks["tail_decode_ss_ms"] = ss_ms
        if not tail_ok:
            tail = (err_tail.strip().splitlines() or ["unknown"])[-1]
            checks["tail_decode_error"] = tail
            reasons.append(f"尾部解码失败: {tail}")

    # ---- e) ASR 用途下无音轨 ----
    asr_no_audio = purpose == "asr" and not decodable_audio

    # ---- 判定 ----
    verdict = "verified"
    if not full_ok:
        verdict = "partial" if has_video else "invalid"
    elif not tail_ok:
        verdict = _worse(verdict, "partial")
    elif duration_anomaly:
        verdict = _worse(verdict, "partial")

    if asr_no_audio:
        verdict = _worse(verdict, "likely")
        reasons.append("无音轨(ASR 不可用)")

    return IntegrityReport(verdict, checks, reasons)


def check_cues(
    cues: list[dict],
    duration_ms: int,
    *,
    tolerance_ms: int = 2000,
    min_coverage: float = 0.5,
) -> dict:
    """校验字幕 cues 的越界 / 覆盖率 / 单调不重叠。

    返回 {"ok": bool, "reasons": [...], "coverage_ratio": float, "max_end_ms": int}
    """
    reasons: list[str] = []
    empty_result = {"ok": False, "reasons": ["空 cues"], "coverage_ratio": 0.0, "max_end_ms": 0}
    if not cues:
        return empty_result

    try:
        starts = [int(c["start_ms"]) for c in cues]
        ends = [int(c["end_ms"]) for c in cues]
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "reasons": ["cues 缺少 start_ms/end_ms"],
                "coverage_ratio": 0.0, "max_end_ms": 0}

    max_end = max(ends)
    first_start = min(starts)
    last_end = max(ends)

    # 1) 越界：末条不得超过时长 + 容差
    if max_end > duration_ms + tolerance_ms:
        reasons.append(f"末条结束 {max_end}ms 超出时长 {duration_ms}ms + 容差 {tolerance_ms}ms")

    # 2) 覆盖率
    if duration_ms > 0:
        coverage = (last_end - first_start) / duration_ms
    else:
        coverage = 0.0
    coverage = max(0.0, min(1.0, coverage))
    if coverage < min_coverage:
        reasons.append(f"覆盖率 {coverage:.3f} < {min_coverage}")

    # 3) 单调不重叠（起点递增，且后一条起点不早于前一条终点 - 1ms 容差）
    ordered = sorted(zip(starts, ends), key=lambda t: t[0])
    for i in range(1, len(ordered)):
        prev_start, prev_end = ordered[i - 1]
        cur_start, cur_end = ordered[i]
        if cur_start < prev_start:
            reasons.append("时间戳非单调（起点回退）")
            break
        if cur_end < cur_start:
            reasons.append(f"越界/非法区间: end {cur_end}ms < start {cur_start}ms")
            break
        if cur_start < prev_end - 1:
            reasons.append(
                f"时间戳重叠: 第{i + 1}条 start {cur_start}ms < 前一条 end {prev_end}ms（容差 1ms）")
            break

    return {
        "ok": not reasons,
        "reasons": reasons,
        "coverage_ratio": round(coverage, 4),
        "max_end_ms": max_end,
    }
