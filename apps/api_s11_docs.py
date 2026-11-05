"""S11 文档解析导入 API（V8）。

流程：上传文档 → 校验格式/大小 → 去重（sha256）→ 保存源文件 → 解析为纯文本
      → 条目复用 videos(platform='document') + documents 明细表入库。

依赖需求基线 DOC-01/02/03/04/05/07/08。
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from apps.core.docparse import (
    FORMAT_LABEL,
    MAX_FILE_BYTES,
    DocParseError,
    detect_format,
    parse_document,
    sha256_bytes,
)
from apps.core.logging_setup import get_logger
from apps.storage import DocumentRepo, VideoRepo

router = APIRouter(prefix="/api", tags=["s11-docs"])
log = get_logger("docs")


def _safe_name(name: str) -> str:
    n = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", Path(name or "document").name)
    return n or "document"


def _doc_dir(request: Request) -> Path:
    d = Path(request.app.state.settings.data_root) / "documents"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _import_one(request: Request, f: UploadFile) -> dict:
    st = request.app.state
    db = st.db
    name = f.filename or "document"

    try:
        fmt = detect_format(name)
    except DocParseError as e:
        return {"name": name, "ok": False, "error": {"code": e.code, "message": e.message}}

    raw = await f.read()
    if len(raw) > MAX_FILE_BYTES:
        return {"name": name, "ok": False,
                "error": {"code": "file_too_large",
                          "message": f"文件超过上限 {MAX_FILE_BYTES // 1024 // 1024} MB"}}
    sha = sha256_bytes(raw)

    # 去重：同一文件已导入则直接复用（DOC-06）
    with st.db_lock:
        existing = DocumentRepo(db).by_sha(sha)
    if existing:
        with st.db_lock:
            v = VideoRepo(db).get(existing["video_id"])
        return {"name": name, "ok": True, "dedup": True,
                "video_id": existing["video_id"],
                "title": (v or {}).get("title") or name,
                "char_count": existing["char_count"],
                "format": existing["format"],
                "format_label": FORMAT_LABEL.get(existing["format"], existing["format"])}

    dest = _doc_dir(request) / f"{uuid.uuid4().hex[:10]}_{_safe_name(name)}"
    try:
        dest.write_bytes(raw)
        parsed = parse_document(dest, original_name=name)
    except DocParseError as e:
        dest.unlink(missing_ok=True)
        return {"name": name, "ok": False, "error": {"code": e.code, "message": e.message}}
    except Exception as e:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        log.warning("文档解析异常 %s: %s", name, str(e)[:160])
        return {"name": name, "ok": False,
                "error": {"code": "internal", "message": f"解析失败：{str(e)[:160]}"}}

    with st.db_lock:
        vrepo = VideoRepo(db)
        video = vrepo.upsert(platform="document", platform_video_id=sha[:16],
                             title=parsed["title"], duration_ms=0, source_url=None)
        DocumentRepo(db).upsert(
            video_id=video["id"], format=parsed["format"], source_path=str(dest),
            size_bytes=len(raw), sha256=sha, char_count=parsed["char_count"],
            content=parsed["text"])
        vrepo.update_status(video["id"], media_status="uploaded", content_scope="full")
    return {"name": name, "ok": True, "dedup": False, "video_id": video["id"],
            "title": parsed["title"], "char_count": parsed["char_count"],
            "format": parsed["format"],
            "format_label": FORMAT_LABEL.get(parsed["format"], parsed["format"])}


@router.post("/documents/import")
async def import_documents(request: Request, files: list[UploadFile] = File(...)):
    """批量导入文档（HTML / Markdown / TXT），逐个返回结果。"""
    if not files:
        raise HTTPException(status_code=400, detail="请至少选择一个文档文件")
    results = []
    for f in files:
        try:
            results.append(await _import_one(request, f))
        except Exception as e:  # noqa: BLE001
            log.warning("文档导入异常 %s: %s", f.filename, str(e)[:160])
            results.append({"name": f.filename, "ok": False,
                            "error": {"code": "internal", "message": str(e)[:200]}})
    imported = [r for r in results if r.get("ok")]
    failed = [r for r in results if not r.get("ok")]
    return {"ok": bool(imported), "count": len(imported),
            "imported": imported, "failed": failed, "results": results}


@router.get("/documents/{video_id}")
def get_document(video_id: str, request: Request):
    st = request.app.state
    with st.db_lock:
        v = VideoRepo(st.db).get(video_id)
        doc = DocumentRepo(st.db).get(video_id)
    if not v or not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {
        "ok": True,
        "video": v,
        "document": {
            "video_id": doc["video_id"], "format": doc["format"],
            "format_label": FORMAT_LABEL.get(doc["format"], doc["format"]),
            "size_bytes": doc["size_bytes"], "char_count": doc["char_count"],
            "created_at": doc["created_at"],
        },
        "content": doc["content"],
    }
