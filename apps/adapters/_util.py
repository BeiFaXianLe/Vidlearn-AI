"""通用工具：子进程调用、哈希、FFprobe。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from pathlib import Path


async def _kill_proc_tree(proc) -> None:
    """结束子进程及其后代（Windows 用 taskkill /T，避免 yt-dlp 孙进程残留）。"""
    try:
        if proc.returncode is None:
            if os.name == "nt":
                k = await asyncio.create_subprocess_exec(
                    "taskkill", "/PID", str(proc.pid), "/T", "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL)
                try:
                    await asyncio.wait_for(k.wait(), timeout=10)
                except Exception:
                    pass
            else:
                proc.kill()
    except Exception:
        pass
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except Exception:
        pass


async def run_cmd(args: list[str], timeout: int = 600, cwd: str | None = None) -> tuple[int, str, str]:
    """参数数组调用子进程（禁止 shell=True）。"""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        await _kill_proc_tree(proc)
        return -1, "", "timeout"
    except asyncio.CancelledError:
        await _kill_proc_tree(proc)
        raise
    return proc.returncode, out.decode("utf-8", "ignore"), err.decode("utf-8", "ignore")


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


async def ffprobe_json(path: Path, ffprobe: str = "ffprobe") -> dict | None:
    rc, out, _ = await run_cmd([
        ffprobe, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ], timeout=60)
    if rc != 0 or not out.strip():
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def resolve_tool(name_or_path: str) -> str | None:
    p = shutil.which(name_or_path)
    if p:
        return p
    if Path(name_or_path).exists():
        return str(Path(name_or_path).resolve())
    return None
