"""文档解析导入测试（DOC-01~08）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

from apps.core.docparse import DocParseError, detect_format, parse_document


@pytest.fixture()
def client():
    import importlib
    import apps.main as main_mod
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c:
        yield c


@pytest.fixture()
def wtmp():
    """工作区内的临时目录（沙箱不允许写系统 temp）。"""
    import shutil
    d = Path(__file__).resolve().parents[1] / ".tmp" / "doc_unit"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------- 解析层（DOC-02/03/08） ----------------
def test_detect_format():
    assert detect_format("a.html") == "html"
    assert detect_format("a.HTM") == "html"
    assert detect_format("b.md") == "markdown"
    assert detect_format("b.markdown") == "markdown"
    assert detect_format("c.txt") == "txt"
    with pytest.raises(DocParseError) as ei:
        detect_format("d.pdf")
    assert ei.value.code == "unsupported_format"


def test_parse_html_strips_tags_and_scripts(wtmp):
    p = wtmp / "p.html"
    p.write_text(
        "<html><head><title>标题T</title><style>.x{color:red}</style></head>"
        "<body><h1>一级标题</h1><p>正文<b>重点</b>&amp;实体</p>"
        "<script>alert(1)</script><ul><li>条目1</li><li>条目2</li></ul></body></html>",
        encoding="utf-8")
    r = parse_document(p)
    assert r["format"] == "html"
    assert r["title"] == "一级标题"
    assert "正文重点&实体" in r["text"]
    assert "<" not in r["text"] and "alert" not in r["text"] and "color:red" not in r["text"]
    assert "条目1" in r["text"] and "条目2" in r["text"]


def test_parse_markdown_strips_markers(wtmp):
    p = wtmp / "n.md"
    p.write_text(
        "# 我的标题\n\n这是**加粗**、*斜体*、[链接](http://x) 与 `code`。\n\n"
        "- 列表A\n- 列表B\n\n```py\nprint(1)\n```\n",
        encoding="utf-8")
    r = parse_document(p)
    assert r["title"] == "我的标题"
    assert "这是加粗、斜体、链接 与 code。" in r["text"]
    assert "列表A" in r["text"] and "**" not in r["text"] and "```" not in r["text"]
    assert "print(1)" in r["text"]


def test_parse_txt_and_empty(wtmp):
    p = wtmp / "a.txt"
    p.write_text("第一行\n第二行", encoding="utf-8")
    r = parse_document(p)
    assert r["format"] == "txt" and r["text"] == "第一行\n第二行"

    empty = wtmp / "e.txt"
    empty.write_text("   \n\n  ", encoding="utf-8")
    with pytest.raises(DocParseError) as ei:
        parse_document(empty)
    assert ei.value.code == "empty_document"


# ---------------- 接口层（DOC-01/04/05/06/07） ----------------
def test_import_markdown_and_list(client):
    r = client.post("/api/documents/import",
                    files=[("files", ("学习笔记.md", "# 笔记\n\n内容段落。".encode("utf-8"), "text/markdown"))])
    assert r.status_code == 200
    d = r.json()
    assert d["count"] == 1 and d["imported"][0]["ok"]
    vid = d["imported"][0]["video_id"]

    # 列表出现文档条目且可按 platform=document 识别（DOC-04）
    lst = client.get("/api/videos").json()["videos"]
    row = next(v for v in lst if v["id"] == vid)
    assert row["platform"] == "document"

    # 详情返回正文（DOC-05）
    g = client.get(f"/api/documents/{vid}").json()
    assert g["document"]["format"] == "markdown"
    assert "内容段落" in g["content"]


def test_unsupported_format_rejected(client):
    r = client.post("/api/documents/import",
                    files=[("files", ("bad.pdf", b"%PDF-1.4", "application/pdf"))])
    d = r.json()
    assert d["count"] == 0
    assert d["failed"][0]["error"]["code"] == "unsupported_format"


def test_dedup_same_file(client):
    payload = "# 去重测试\n\n同一内容".encode("utf-8")
    r1 = client.post("/api/documents/import",
                     files=[("files", ("dup.md", payload, "text/markdown"))]).json()
    r2 = client.post("/api/documents/import",
                     files=[("files", ("dup.md", payload, "text/markdown"))]).json()
    assert r1["imported"][0]["video_id"] == r2["imported"][0]["video_id"]
    assert r2["imported"][0]["dedup"] is True


def test_delete_removes_document_and_file(client):
    r = client.post("/api/documents/import",
                    files=[("files", ("delme.txt", "待删除文档内容".encode("utf-8"), "text/plain"))]).json()
    vid = r["imported"][0]["video_id"]
    db = client.app.state.db
    src = db.execute("SELECT source_path FROM documents WHERE video_id=?", (vid,)).fetchone()
    assert src and Path(src[0]).exists()

    assert client.delete(f"/api/videos/{vid}").json()["ok"]
    assert client.get(f"/api/documents/{vid}").status_code == 404
    assert not Path(src[0]).exists()  # 源文件被清理（DOC-07）
