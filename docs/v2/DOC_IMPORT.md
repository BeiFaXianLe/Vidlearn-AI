# 文档解析导入（V2 增强）

> 任务：doc-import / doc-import-mvp · 基线 R1 · 2026-11-04
> 流程：Workflow V2.0 G0–G7（见 `workflow-runs/doc-import/`）

## 1. 能力范围

- 在「导入资料」弹窗新增 **文档导入** 模式，可多选文件。
- 支持格式：**HTML（.html/.htm） / Markdown（.md/.markdown） / TXT（.txt）**。
- 解析为纯文本后作为独立「文档」资料条目入库，与视频并列显示于资料库，可按「文档」筛选。
- 详情页展示 **原文 + 标题/格式/字数**，并保留学习笔记。
- 重复导入按 sha256 去重；删除资料时联动删除解析文本与源文件。

不在本期：PDF/Word/PPT/Excel、OCR、文档 AI 摘要/章节/问答、全文检索、独立知识库页面。

## 2. 数据模型（V8）

- 复用 `videos` 表：`platform='document'`，`platform_video_id=sha256[:16]`（去重键）。
- 新增 `documents` 表：

| 列 | 说明 |
|---|---|
| video_id (PK, FK→videos.id ON DELETE CASCADE) | 关联资料条目 |
| format | html / markdown / txt |
| source_path | 源文件（`data/documents/`） |
| size_bytes / sha256 / char_count | 文件与正文字数 |
| content | 解析后的纯文本 |

## 3. 接口契约

### POST /api/documents/import
- Content-Type：`multipart/form-data`，字段 `files`（可多个）。
- 校验：扩展名白名单、单文件 ≤ 20 MB、正文 ≤ 50 万字符。
- 响应 200：

```json
{
  "ok": true,
  "count": 1,
  "imported": [{
    "name": "课程笔记.md", "ok": true, "dedup": false,
    "video_id": "…", "title": "Redis 持久化", "char_count": 37,
    "format": "markdown", "format_label": "Markdown"
  }],
  "failed": [],
  "results": []
}
```
- 单条失败（如非法格式）进入 `failed`，`error.code` ∈ `unsupported_format | file_too_large | decode_failed | empty_document | content_too_large | internal`。

### GET /api/documents/{video_id}
- 200：`{ ok, video, document:{format,format_label,size_bytes,char_count,created_at}, content }`
- 404：非文档或不存在。

### 复用
- 列表：`GET /api/videos`（`platform='document'`）；
- 删除：`DELETE /api/videos/{id}`（级联删除 documents + 清理源文件）；
- 笔记：`POST/GET /api/videos/{id}/notes`。

## 4. 解析实现

`apps/core/docparse.py`（纯标准库，无新增依赖）：
- HTML：`html.parser` 提取可见文本，跳过 script/style/noscript/template/svg，块级标签换行，实体自动解码。
- Markdown：正则去标题/强调/链接/图片/代码围栏/列表标记，保留段落与代码内容。
- TXT：编码自动探测（utf-8-sig → utf-8 → gb18030 → gbk）。
- 统一规范化空行与首尾空白。

> 说明：需求确认时用户允许新增 pypdf/python-docx，但本期格式为 HTML/MD/TXT，标准库即可满足，按最小改动原则暂不引入；纳入 PDF/Word 切片时再加。

## 5. 验证摘要

- 全量测试：`pytest -q` → **230 passed**（新增 8 条，见 `tests/test_documents.py`）。
- 真实接口：uvicorn + httpx 实测导入/列表/详情/去重/删除/非法格式均通过。
- 页面：Playwright 截图确认文档卡片、文档筛选、详情原文、导入弹窗文档 Tab。
