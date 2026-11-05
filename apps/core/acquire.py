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


def _dir_bytes(path: Path) -> int:
    """统计目录内所有文件大小（用于下载“无进展”看门狗）。"""
    try:
        return sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file())
    except OSError:
        return 0


def purge_stale_job_dirs(temp_dir: Path, max_age_sec: int = 24 * 3600) -> int:
    """清理历史临时下载目录。

    - 旧版 `job_*`：异常退出残留，启动时全部清理；
    - 新版 `dl_*`：断点续传目录，只清理超过 max_age_sec 的陈年目录，
      保留最近未完成的下载，便于重启后继续续传。
    """
    import shutil
    import time
    d = Path(temp_dir)
    if not d.exists():
        return 0
    n = 0
    for sub in d.glob("job_*"):
        if sub.is_dir():
            shutil.rmtree(sub, ignore_errors=True)
            n += 1
    now = time.time()
    for sub in d.glob("dl_*"):
        if not sub.is_dir():
            continue
        try:
            if now - sub.stat().st_mtime > max_age_sec:
                shutil.rmtree(sub, ignore_errors=True)
                n += 1
        except OSError:
            pass
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

    def __init__(self, temp_dir: Path, original_dir: Path, ffmpeg: str = "ffmpeg",
                 timeout_sec: int = 3600, stall_timeout_sec: int = 120):
        self.temp_dir = Path(temp_dir)
        self.original_dir = Path(original_dir)
        self.ffmpeg = ffmpeg
        self.timeout_sec = timeout_sec
        self.stall_timeout_sec = stall_timeout_sec
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.original_dir.mkdir(parents=True, exist_ok=True)

    async def acquire(self, adapter: VideoAdapter, source: str,
                      *, max_height: int | None = None,
                      download_sections: str | None = None,
                      retries: int = 1) -> MediaResult:
        last: AcquireError | None = None
        # 断点续传：同一来源复用固定工作目录，重试时 yt-dlp 从 .part 继续，
        # 不再每次新建目录 + 失败即删（否则大视频永远下不完）。
        work = self.temp_dir / f"dl_{source_hash(source)}"
        work.mkdir(parents=True, exist_ok=True)
        opts = FetchOpts(max_height=max_height, out_dir=work,
                         download_sections=download_sections,
                         timeout_sec=self.timeout_sec)
        for attempt in range(retries + 1):
            try:
                res = await self._fetch_watched(adapter, source, opts, work)
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
                shutil.rmtree(work, ignore_errors=True)   # 成功后清理临时区
                return res
            except AcquireError as e:
                last = e
                log.warning("获取失败 attempt=%d/%d code=%s msg=%s",
                            attempt + 1, retries + 1, e.code.value, e.message)
                if not e.retryable:
                    break
        # 全部失败：保留 work 目录中的 .part，后续重试可续传
        raise last or AcquireError(ErrorCode.INTERNAL, "获取失败")

    async def _fetch_watched(self, adapter: VideoAdapter, source: str,
                             opts: FetchOpts, work: Path) -> MediaResult:
        """执行下载并做“无进展”看门狗。

        CDN 偶发假连接时进程会一直挂着但 0 字节；这里监控工作目录大小，
        超过 stall_timeout_sec 无增长就取消（连带杀掉子进程树），
        抛可续传的 TIMEOUT，让上层重试从 .part 继续 / 换节点重连。
        """
        import asyncio
        import time as _time
        task = asyncio.ensure_future(adapter.fetch_media(source, opts))
        stall = max(30, int(self.stall_timeout_sec))
        last_size = _dir_bytes(work)
        last_change = _time.monotonic()
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=2.0)
                if task in done:
                    return task.result()
                size = _dir_bytes(work)
                now = _time.monotonic()
                if size != last_size:
                    last_size = size
                    last_change = now
                elif now - last_change >= stall:
                    task.cancel()
                    try:
                        await task
                    except BaseException:  # noqa: BLE001
                        pass
                    raise AcquireError(
                        ErrorCode.TIMEOUT,
                        f"下载 {stall}s 无进展（已保留断点，可续传重试）",
                        retryable=True)
        finally:
            if not task.done():
                task.cancel()


def source_hash(source: str) -> str:
    import hashlib
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]
