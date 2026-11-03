"""S6 媒体播放：受控 HTTP Range 流式接口。

安全要点：
- 不把 media 目录作为静态目录暴露。
- 只允许访问数据库登记的 media_assets 的 storage_path（禁止任意路径）。
- 支持 Range（可拖动进度），返回 206 + Content-Range。
"""
from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from apps.storage import MediaAssetRepo

router = APIRouter(prefix="/api", tags=["s6"])

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
CHUNK = 1024 * 256


def _allowed_path(request: Request, video_id: str, asset_id: str | None) -> Path:
    db = request.app.state.db
    arepo = MediaAssetRepo(db)
    assets = [a for a in arepo.for_video(video_id) if a["asset_type"] == "original_media"]
    if not assets:
        raise HTTPException(status_code=404, detail="该视频无本地媒体")
    if asset_id:
        assets = [a for a in assets if a["id"] == asset_id]
        if not assets:
            raise HTTPException(status_code=404, detail="资产不存在")
    asset = sorted(assets, key=lambda a: a["created_at"])[-1]
    root = Path(request.app.state.settings.data_root).resolve()
    p = Path(asset["storage_path"]).resolve()
    # 二次校验：路径必须在 data_root 内（防目录穿越）
    if root not in p.parents and p != root:
        raise HTTPException(status_code=403, detail="非法媒体路径")
    if not p.exists():
        raise HTTPException(status_code=404, detail="媒体文件缺失")
    return p


def _iter_file(path: Path, start: int, end: int):
    with open(path, "rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = f.read(min(CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/videos/{video_id}/media")
def stream_media(video_id: str, request: Request, asset_id: str | None = None):
    path = _allowed_path(request, video_id, asset_id)
    file_size = path.stat().st_size
    mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"

    range_header = request.headers.get("range")
    if not range_header:
        headers = {
            "Content-Length": str(file_size),
            "Content-Type": mime,
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store",
        }
        return StreamingResponse(_iter_file(path, 0, file_size - 1), status_code=200,
                                 headers=headers, media_type=mime)

    m = RANGE_RE.match(range_header.strip())
    if not m:
        raise HTTPException(status_code=416, detail="非法 Range")
    start_s, end_s = m.group(1), m.group(2)
    if start_s == "" and end_s == "":
        raise HTTPException(status_code=416, detail="非法 Range")
    if start_s == "":
        # 后缀范围：最后 N 字节
        n = int(end_s)
        start = max(0, file_size - n)
        end = file_size - 1
    else:
        start = int(start_s)
        end = int(end_s) if end_s else file_size - 1
    if start > end or start >= file_size:
        return StreamingResponse(iter(()), status_code=416,
                                 headers={"Content-Range": f"bytes */{file_size}"})
    end = min(end, file_size - 1)
    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Content-Type": mime,
        "Cache-Control": "no-store",
    }
    return StreamingResponse(_iter_file(path, start, end), status_code=206,
                             headers=headers, media_type=mime)
