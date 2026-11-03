"""本地 ASR（S4）：FFmpeg 提取 16k PCM → 切片(带重叠) → faster-whisper → 合并去重。

S0 实测约束：
- 不使用 PyAV，音频统一由 FFmpeg 解码为 16kHz 单声道 PCM。
- 切片必须重叠（默认 2s），合并时按文本去重边界，防句子截断/重复。
- 合并后校验时间戳单调、不重叠、不越界。
"""
from __future__ import annotations

import asyncio
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np

from apps.adapters._util import run_cmd


@dataclass
class ASROpts:
    language: str = "zh"
    model: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    segment_sec: int = 30
    overlap_sec: int = 2
    vad_filter: bool = True
    initial_prompt: str | None = None   # 术语热词（提升专有名词识别）


@dataclass
class ASRResult:
    cues: list[dict] = field(default_factory=list)
    model: str = ""
    language: str = ""
    rtf: float | None = None
    status: str = "complete"      # complete | partial | failed
    reason: str | None = None


class ASRProvider(Protocol):
    async def transcribe(self, media_path: Path, opts: ASROpts) -> ASRResult: ...


def _read_wav_mono16k(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1:
            raise ValueError("需要 16kHz 单声道 WAV")
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


async def extract_audio_16k(media_path: Path, out_wav: Path, ffmpeg: str = "ffmpeg") -> Path:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    rc, out, err = await run_cmd([
        ffmpeg, "-y", "-v", "error", "-i", str(media_path),
        "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(out_wav),
    ], timeout=1800)
    if rc != 0 or not out_wav.exists():
        from apps.adapters.base import AcquireError, ErrorCode
        raise AcquireError(ErrorCode.MEDIA_NO_AUDIO, f"音频提取失败: {err[:200]}")
    return out_wav


def split_with_overlap(audio: np.ndarray, sr: int, segment_sec: int, overlap_sec: int):
    """切成 (chunk_audio, offset_sec) 列表，段间重叠 overlap_sec。"""
    seg = max(1, segment_sec) * sr
    step = max(1, (segment_sec - overlap_sec)) * sr
    chunks = []
    i = 0
    while i < len(audio):
        chunk = audio[i:i + seg]
        if len(chunk) < sr * 0.3:  # 太短忽略
            break
        chunks.append((chunk, i / sr))
        if i + seg >= len(audio):
            break
        i += step
    return chunks


def _dedupe_boundary(merged: list[dict]) -> list[dict]:
    """相邻段重复文本去重：若后段开头与已合并尾部高度重合，裁掉重复部分。"""
    out: list[dict] = []
    for c in merged:
        if out:
            prev = out[-1]
            a, b = prev["text"].strip(), c["text"].strip()
            # 完全相同的短句
            if a and a == b:
                continue
            # 前句尾部 == 后句头部（长度 >= 4）
            k = 0
            for n in range(min(len(a), len(b)), 3, -1):
                if a[-n:] == b[:n]:
                    k = n
                    break
            if k:
                c = dict(c)
                c["text"] = b[k:]
                if not c["text"].strip():
                    continue
        out.append(c)
    return out


def _fix_overlaps(cues: list[dict]) -> list[dict]:
    """重叠切片会产生时间重叠：把当前段起点裁到上一段终点，无效则丢弃。"""
    out: list[dict] = []
    for c in cues:
        if out:
            prev_end = out[-1]["end_ms"]
            if c["start_ms"] < prev_end:
                c = dict(c)
                c["start_ms"] = prev_end
                if c["start_ms"] >= c["end_ms"]:
                    continue
        out.append(c)
    return out


def _validate(cues: list[dict], duration_ms: int | None) -> tuple[bool, list[str]]:
    issues = []
    for i, c in enumerate(cues):
        if c["end_ms"] < c["start_ms"]:
            issues.append(f"段{i} end<start")
        if i > 0 and c["start_ms"] + 1 < cues[i - 1]["end_ms"]:
            issues.append(f"段{i} 与上段重叠")
        if duration_ms and c["end_ms"] > duration_ms + 2000:
            issues.append(f"段{i} 越界")
    return (len(issues) == 0), issues


class FasterWhisperASR:
    """faster-whisper 实现。模型懒加载并缓存。"""

    def __init__(self, ffmpeg: str = "ffmpeg", model_dir: str | None = None,
                 work_dir: str | None = None):
        self._ffmpeg = ffmpeg
        self._model_dir = model_dir or None
        self._work_dir = work_dir or None
        self._models: dict[str, object] = {}

    def _get_model(self, model: str, device: str, compute_type: str):
        key = f"{model}|{device}|{compute_type}"
        if key not in self._models:
            from faster_whisper import WhisperModel
            # 解析模型来源：显式 model_dir > 项目内 models/faster-whisper-<model> > 模型名(联网/HF缓存)
            path_or_name = self.resolve_model(model)
            self._models[key] = WhisperModel(path_or_name, device=device, compute_type=compute_type)
        return self._models[key]

    def resolve_model(self, model: str) -> str:
        """返回可用的模型来源（目录或模型名）。"""
        if self._model_dir:
            return self._model_dir
        # 项目根：apps/core/asr.py -> parents[2]
        from pathlib import Path as _P
        root = _P(__file__).resolve().parents[2]
        # 常见命名：faster-whisper-small / small
        for name in (f"faster-whisper-{model}", model):
            cand = root / "models" / name
            if (cand / "model.bin").exists():
                return str(cand)
        return model

    async def transcribe(self, media_path: Path, opts: ASROpts) -> ASRResult:
        # 音频工作文件放在专用工作目录，不污染媒体目录
        if self._work_dir:
            work = Path(self._work_dir)
            work.mkdir(parents=True, exist_ok=True)
            wav = work / f"{media_path.stem}.asr16k.wav"
        else:
            import tempfile
            wav = Path(tempfile.gettempdir()) / f"{media_path.stem}.asr16k.wav"
        wav = await extract_audio_16k(media_path, wav, ffmpeg=self._ffmpeg)
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, self._transcribe_sync, wav, opts)
        finally:
            try:
                wav.unlink(missing_ok=True)
            except Exception:
                pass

    def _transcribe_sync(self, wav: Path, opts: ASROpts) -> ASRResult:
        import time
        audio = _read_wav_mono16k(wav)
        duration_s = len(audio) / 16000
        model = self._get_model(opts.model, opts.device, opts.compute_type)

        chunks = split_with_overlap(audio, 16000, opts.segment_sec, opts.overlap_sec)
        merged: list[dict] = []
        t0 = time.time()
        for chunk, offset in chunks:
            _kw = {"language": opts.language, "vad_filter": opts.vad_filter}
            if opts.initial_prompt:
                _kw["initial_prompt"] = opts.initial_prompt
            segs, _ = model.transcribe(chunk, **_kw)
            for s in segs:
                text = s.text.strip()
                if not text:
                    continue
                merged.append({
                    "start_ms": int((offset + s.start) * 1000),
                    "end_ms": int((offset + s.end) * 1000),
                    "text": text,
                    "confidence": round(float(getattr(s, "avg_logprob", 0.0) or 0.0), 4),
                })
        infer = time.time() - t0
        merged.sort(key=lambda c: c["start_ms"])
        merged = _dedupe_boundary(merged)
        merged = _fix_overlaps(merged)
        # 繁简统一为简体（入库前处理，保证库与导出都是简体）
        from apps.core.textnorm import simplify_cues, strip_time_tags
        merged = simplify_cues(merged)
        for c in merged:
            c["text"] = strip_time_tags(c["text"])
        merged = [c for c in merged if c["text"].strip()]
        ok, issues = _validate(merged, int(duration_s * 1000))
        status = "complete" if ok and merged else ("partial" if merged else "failed")
        return ASRResult(cues=merged, model=opts.model, language=opts.language,
                         rtf=round(infer / duration_s, 3) if duration_s else None,
                         status=status, reason=None if ok else "; ".join(issues))
