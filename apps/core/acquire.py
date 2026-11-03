"""下载/获取管理（S2-08）：进度、失败、重试与产物落库前的临时区管理。"""
from __future__ import annotations

import shutil
from pathlib import Path

from apps.adapters._util import run_cmd
from apps.adapters.base import AcquireError, ErrorCode, FetchOpts, MediaResult, VideoAdapter
from apps.core.logging_setup import get_logger

log = get_logger("acquire")

# 浏览器 <video> 直接可播的容器
BROWSER_PLAYABLE = {".mp4", ".webm", ".m4a", ".mp3", ".ogg"}


def purge_stale_job_dirs(temp_dir: Path) -> int:
    """清理异常退出留下的 job_* 临时目录（进程被杀时 finally 不会执行）。"""
    import shutil
    d = Path(temp_dir)
    if not d.exists():
        return 0
    n = 0
    for sub in d.glob("job_*"):
        if sub.is_dir():
            shutil.rmtree(sub, ignore_errors=True)
            n += 1
    return n


async def ensure_playable(path: Path, ffmpeg: str = "ffmpeg") -> Path:
    """把 MKV/MOV/AVI 等浏览器不支持的容器 remux 成 MP4（无损、stream copy）。

    - 已在可播列表 → 原样返回
    - 保留字幕轨（转 mov_text，MP4 支持，后续仍可提取）
    - remux 失败 → 原样返回（不阻断，前端给出提示）
    """
    if path.suffix.lower() in BROWSER_PLAYABLE:
        return path
    out = path.with_suffix(".mp4")
    # 先尝试带字幕转换；失败则退回纯音视频 copy
    rc, _, err = await run_cmd([
        ffmpeg, "-y", "-v", "error", "-i", str(path),
        "-map", "0", "-c", "copy", "-c:s", "mov_text",
        "-movflags", "+faststart", str(out),
    ], timeout=1800)
    if rc != 0 or not out.exists() or out.stat().st_size == 0:
        if out.exists():
            out.unlink(missing_ok=True)
        rc, _, err = await run_cmd([
            ffmpeg, "-y", "-v", "error", "-i", str(path),
            "-c", "copy", "-movflags", "+faststart", str(out),
        ], timeout=1800)
    if rc == 0 and out.exists() and out.stat().st_size > 0:
        log.info("remux→mp4 成功: %s -> %s", path.name, out.name)
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        return out
    log.warning("remux→mp4 失败(%s)，保留原容器: %s", err[:120], path.name)
    if out.exists():
        out.unlink(missing_ok=True)
    return path


class AcquisitionManager:
    """统一编排「临时区下载 → 校验 → 原子移入正式区」。"""

    def __init__(self, temp_dir: Path, original_dir: Path, ffmpeg: str = "ffmpeg"):
        self.temp_dir = Path(temp_dir)
        self.original_dir = Path(original_dir)
        self.ffmpeg = ffmpeg
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.original_dir.mkdir(parents=True, exist_ok=True)

    async def acquire(self, adapter: VideoAdapter, source: str,
                      *, max_height: int | None = None,
                      download_sections: str | None = None,
                      retries: int = 1) -> MediaResult:
        last: AcquireError | None = None
        for attempt in range(retries + 1):
            import uuid as _uuid
            work = self.temp_dir / f"job_{source_hash(source)}_{attempt}_{_uuid.uuid4().hex[:6]}"
            work.mkdir(parents=True, exist_ok=True)
            opts = FetchOpts(max_height=max_height, out_dir=work,
                             download_sections=download_sections)
            try:
                res = await adapter.fetch_media(source, opts)
                # 转成浏览器可播容器（MKV/MOV → MP4），保留字幕轨
                before = res.file_path
                playable = await ensure_playable(res.file_path, self.ffmpeg)
                if playable != before:
                    from apps.adapters._util import sha256_file
                    res.sha256 = sha256_file(playable)
                res.file_path = playable
                # 原子移入正式区
                dest = self.original_dir / f"{res.sha256[:16]}{playable.suffix}"
                if dest.exists():
                    playable.unlink(missing_ok=True)  # 去重
                else:
                    shutil.move(str(playable), str(dest))
                res.file_path = dest
                log.info("获取成功 source=%s sha=%s size=%d", source_hash(source),
                         res.sha256[:12], dest.stat().st_size)
                return res
            except AcquireError as e:
                last = e
                log.warning("获取失败 attempt=%d/%d code=%s msg=%s",
                            attempt + 1, retries + 1, e.code.value, e.message)
                if not e.retryable:
                    break
            finally:
                shutil.rmtree(work, ignore_errors=True)
        raise last or AcquireError(ErrorCode.INTERNAL, "获取失败")


def source_hash(source: str) -> str:
    import hashlib
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]
