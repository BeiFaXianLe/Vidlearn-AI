"""文档解析：HTML / Markdown / TXT → 纯文本（V8）。

设计约束（对应需求基线 DOC-02/03/08）：
- 纯标准库实现，不引入第三方依赖；
- 输出统一规整的纯文本，保留段落换行；
- 明确区分错误码，便于接口层回传可读提示；
- 单文件与正文字符设上限，防止异常大文件拖垮进程。
"""
from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path

MAX_FILE_BYTES = 20 * 1024 * 1024      # 单文件 20 MB
MAX_CHARS = 500_000                    # 解析正文 50 万字符

EXT_FORMAT = {
    ".html": "html", ".htm": "html",
    ".md": "markdown", ".markdown": "markdown",
    ".txt": "txt",
}
SUPPORTED_EXT = set(EXT_FORMAT)
FORMAT_LABEL = {"html": "HTML", "markdown": "Markdown", "txt": "TXT"}


class DocParseError(Exception):
    """解析失败，携带稳定错误码与可读信息。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def detect_format(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    fmt = EXT_FORMAT.get(ext)
    if not fmt:
        raise DocParseError(
            "unsupported_format",
            f"不支持的文档格式：{ext or '未知'}（仅支持 HTML / Markdown / TXT）")
    return fmt


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise DocParseError("decode_failed", "无法识别文件编码（请转为 UTF-8 后重试）")


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(ln.rstrip() for ln in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------- HTML ----------------
_BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article",
    "header", "footer", "aside", "pre", "blockquote", "hr", "form",
    "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd",
}
_SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0
        self.title: str | None = None
        self.h1: str | None = None
        self._in_title = False
        self._in_h1 = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self.skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        elif tag == "h1" and self.h1 is None:
            self._in_h1 = True
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag.lower() in ("br", "hr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            if self.skip_depth > 0:
                self.skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip_depth > 0:
            return
        if self._in_title:
            t = data.strip()
            if t and self.title is None:
                self.title = t
            return
        if self._in_h1 and self.h1 is None:
            t = data.strip()
            if t:
                self.h1 = t
        if data.strip():
            self.parts.append(data)


def _html_to_text(src: str) -> tuple[str, str | None]:
    p = _HTMLTextExtractor()
    p.feed(src)
    p.close()
    text = _normalize("".join(p.parts))
    return text, (p.h1 or p.title)


# ---------------- Markdown ----------------
def _strip_inline_md(s: str) -> str:
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", s)          # 图片 → alt
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)           # 链接 → 文本
    s = re.sub(r"`{1,3}([^`]*)`{1,3}", r"\1", s)             # 行内代码
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)                 # 粗体
    s = re.sub(r"__([^_]+)__", r"\1", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", s)        # 斜体
    s = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"\1", s)
    s = re.sub(r"~~([^~]+)~~", r"\1", s)                     # 删除线
    s = re.sub(r"<[^>]+>", "", s)                            # 残留 HTML 标签
    return s


def _markdown_to_text(src: str) -> str:
    out: list[str] = []
    in_fence = False
    for line in src.split("\n"):
        if re.match(r"^\s*(```|~~~)", line):
            in_fence = not in_fence
            continue
        if in_fence:
            out.append(line)
            continue
        m = re.match(r"^\s{0,3}#{1,6}\s+(.*)$", line)
        if m:
            out.append(_strip_inline_md(m.group(1)).strip())
            continue
        if re.match(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$", line):
            out.append("")
            continue
        m = re.match(r"^\s{0,3}>\s?(.*)$", line)
        if m:
            out.append(_strip_inline_md(m.group(1)))
            continue
        m = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$", line)
        if m:
            out.append("• " + _strip_inline_md(m.group(1)))
            continue
        out.append(_strip_inline_md(line))
    return _normalize("\n".join(out))


def parse_document(path: Path, *, original_name: str | None = None) -> dict:
    """解析单个文档文件，返回 {format,title,text,char_count,size_bytes}。"""
    name = original_name or path.name
    fmt = detect_format(name)
    try:
        size = path.stat().st_size
    except OSError:
        raise DocParseError("file_invalid", "文件不存在或不可读")
    if size > MAX_FILE_BYTES:
        raise DocParseError(
            "file_too_large", f"文件超过上限 {MAX_FILE_BYTES // 1024 // 1024} MB")
    raw = path.read_bytes()
    src = _decode(raw)

    stem = Path(name).stem or "未命名文档"
    title = stem
    if fmt == "html":
        text, t = _html_to_text(src)
        if t:
            title = t
    elif fmt == "markdown":
        text = _markdown_to_text(src)
        m = re.search(r"^\s{0,3}#\s+(.+)$", src, re.M)
        if m:
            title = _strip_inline_md(m.group(1)).strip() or stem
    else:
        text = _normalize(src)

    if not text.strip():
        raise DocParseError("empty_document", "文档未解析出任何文本内容")
    if len(text) > MAX_CHARS:
        raise DocParseError(
            "content_too_large", f"解析正文超过 {MAX_CHARS} 字符上限")
    return {"format": fmt, "title": title, "text": text,
            "char_count": len(text), "size_bytes": size}
