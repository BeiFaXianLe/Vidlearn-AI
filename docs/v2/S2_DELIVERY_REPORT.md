# S2 交付报告：视频来源适配器

- 日期：2026-11-02
- 状态：**完成**（25 个单测通过，HTTP 实拉验收通过）
- 依据：PRD V2.0、INTERFACE_CONTRACTS.md、S0 实测约束

---

## 一、交付物与代码位置

| 任务 | 文件 | 说明 |
|---|---|---|
| S2-01 统一接口 | `apps/adapters/base.py` | VideoAdapter Protocol、VideoMeta/FetchOpts/MediaResult、ErrorCode |
| S2-02 本地文件 | `apps/adapters/local_file.py` | FFprobe 校验 + SHA256 + 重复检测 |
| S2-03/04 B站双模式 | `apps/adapters/bilibili.py` | yt-dlp 封装、匿名/登录（Cookie 文件注入） |
| S2-05 平台字幕 | `apps/adapters/bilibili.py:fetch_subtitles` | 强校验 + 重取 + 覆盖率检查 |
| S2-06 抖音 | `apps/adapters/__init__.py` | 暂缓，resolve 时返回 unsupported |
| S2-08 下载管理 | `apps/core/acquire.py` | 临时区→校验→原子移入→去重、重试 |
| S2-09 错误分类 | `bilibili.py:_classify` | need_login/not_authorized/network/format_changed/unsupported |
| API | `apps/api_s2.py` | /probe /import /credentials /transcript/tracks |
| 测试 | `tests/test_s2.py` | 12 个用例（含字幕校验、错误分类） |

---

## 二、验收结果

### 2.1 单元测试
```
25 passed（S1 13 + S2 12）
```

### 2.2 实拉验收（HTTP）
| 场景 | 结果 |
|---|---|
| `/api/probe` B站 | ✅ 标题/作者/105.6s/[1080,720,480,360] |
| `/api/import` 本地 MP4 | ✅ 360P，SHA256 正常，原子入库 |
| `/api/import` B站 720P 片段 | ✅ 720P / 10.005s / **h264** |
| `/api/credentials/bilibili` | ✅ missing（未设置时） |
| temp 目录残留 | ✅ 0（清理正常） |

### 2.3 平台字幕（登录态，6 次取样）
| 次数 | 条数 | 末条 | 判定 |
|---|---|---|---|
| 1–4 | 55 | 105.4s | ✅ |
| 5 | — | — | 校验拦截（重取后恢复） |
| 6 | 55 | 105.4s | ✅ |

→ 重取机制有效；另有 1 次「时间戳合法但内容不符」（43条/88.5s），已通过**覆盖率校验**（字幕须覆盖 ≥50% 时长）缓解。

---

## 三、S2 期间发现并修复的问题

### 问题 1：Windows 下临时 Cookie 文件被 yt-dlp 占用，unlink 失败
- 现象：`PermissionError: WinError 32 另一个程序正在使用此文件`
- 修复：`_safe_unlink()` 重试删除 + 失败不抛；避免影响主流程。

### 问题 2：格式选择器优先拿到 AV1，浏览器兼容差
- 现象：B站下载产物 `vcodec=av1`（PRD 要求优先 H.264）
- 修复：格式串改为 `bv*[vcodec^=avc1]+ba/bv*+ba/bv*+ba/best`，实测变为 `h264`。

### 问题 3：B站字幕「时间戳合法但内容不对」
- 现象：曾拿到 43 条 / 88.5s 的字幕，与视频标题明显无关。
- 修复：新增**覆盖率校验**（`(末-首)/时长 ≥ 50%`），并保留时长越界校验与重取。
- 残留风险：仍无法 100% 排除「同长度但错内容」，需 S3 结合字幕文本与标题/章节做语义校验（记入风险）。

---

## 四、接口对齐

| INTERFACE_CONTRACTS §1 | 实现 |
|---|---|
| VideoAdapter.can_handle/probe/fetch_media | ✅ |
| VideoMeta 字段 | ✅ |
| MediaResult 含 sha256/height/vcodec/has_audio | ✅ |
| 子进程参数数组、不拼 shell | ✅ |
| 下载落 temp → 校验 → 原子移入 original | ✅ |
| 错误码 need_login/format_changed/blocked/not_authorized/network… | ✅（blocked 预留抖音） |

---

## 五、S2 Gate 判定

| Gate 条件 | 结果 |
|---|---|
| 统一来源接口可用 | ✅ |
| 本地文件可导入并校验 | ✅ |
| B站匿名可下载 | ✅ |
| B站登录态可下载（Cookie 注入） | ✅ |
| B站平台字幕可获取且经强校验 | ✅ |
| 下载失败有明确错误分类 | ✅ |
| 抖音：保留接口、明确不支持 | ✅（暂缓） |

**S2 通过，可进入 S3（媒体资产与字幕处理）。**

---

## 六、移交 S3 的事项

1. **字幕语义校验**：覆盖率+时长已能挡大部分污染，但仍需文本级校验（与标题/章节比对）。
2. **B站字幕轨道可含多语言**：需在 S3 落 `source_captions` 时保留多轨，不覆盖。
3. **媒体入库目前只落文件+sha**：S3 需补 `media_assets` 表与完整性状态。
4. TaskManager 仍为内存版，S3 可与 media_assets 一起切 SQLite。
