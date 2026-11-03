# S3 交付报告：媒体资产与字幕处理

- 日期：2026-11-02
- 状态：**完成**（57 个单测通过，本地+B站 端到端实测通过）
- 依据：PRD V2.0 §4、INTERFACE_CONTRACTS.md、S0 实测约束

---

## 一、交付物与代码位置

| 任务 | 文件 | 说明 |
|---|---|---|
| S3-01 数据模型/DB | `apps/storage/db.py`、`repositories.py` | videos / media_assets / source_captions / transcript_segments + 外键/索引/迁移 |
| S3-01 入库编排 | `apps/core/intake.py` | MediaIntake / CaptionIntake / choose_primary（来源优先级） |
| S3-02/03 完整性 | `apps/core/integrity.py` | 多指标 check_media + check_cues（并行 Agent 交付） |
| S3-04/05 字幕解析 | `apps/core/subtitles.py` | SRT/VTT/ASS 解析、to_srt、normalize、内嵌提取（并行 Agent 交付） |
| S3-06/07 字幕标准化 | 同上 | `cues_from_bilibili` 秒→毫秒标准化 |
| S3-08 覆盖率/完整性 | `integrity.check_cues` | ≥50% 覆盖 + 越界 + 重叠校验 |
| S3-09 状态流转 | `intake.py` | 同步 videos.media_status / transcript_status |
| API | `apps/api_s3.py` | /intake /integrity /videos /videos/{id} /transcript |
| 测试 | `tests/test_s3_storage.py`、`test_integrity.py`、`test_subtitles.py` | 共 32 个 S3 用例 |

---

## 二、验收结果

### 2.1 单元测试
```
57 passed in 1.80s   （S1 13 + S2 12 + S3 32）
```

### 2.2 本地文件端到端（HTTP）
```
POST /api/intake  {source: sample_with_sub.mkv, purpose: playback}
→ intake ok: True
→ integrity: verified
→ captions: {"source":"embedded","tracks":[{"cues":2,"segments":2}]}
GET /api/videos/{id}/transcript
→ [(500,2500,"first subtitle line"), (3000,5500,"second subtitle line")]
```
✅ 内嵌字幕提取 → 标准化 → 入库 → 分段查询，时间戳与源 SRT 完全一致。

### 2.3 B站真实端到端（HTTP，登录态）
```
POST /api/credentials  → status: valid（DPAPI 加密）
POST /api/intake {source: BV1dJ7C6FEUX, max_height:360, download_sections:"*0-20"}
→ ok: True | integrity: verified | media: 360P h264
→ captions: {"source":"bilibili_ai","cues":55,"segments":55}
→ 分段首 3 条: [(0,"来啦来啦"),(980,"它是一个完全免费的在线视频下载工"),(3940,"注意不用安装任何插件或软件")]
```
✅ 下载 → 完整性 verified → 平台字幕 55 条 → 55 分段，内容与视频主题吻合。

### 2.4 数据库落地
```
videos: 2 | media_assets: 2 | source_captions: 2 | transcript_segments: 57
```

---

## 三、S3 期间发现并修复的问题

### 问题 1：SQLite 跨线程使用崩溃（严重，已修复）
- 现象：`SQLite objects created in a thread can only be used in that same thread`
- 原因：FastAPI 同步路由跑在线程池，连接默认 `check_same_thread=True`
- 修复：`connect(check_same_thread=False)` + `busy_timeout`；启动时建单连接，端点在 **db_lock（RLock）** 内做写操作

### 问题 2：内嵌字幕未入库（功能缺失，已补）
- 现象：MKV 有 subrip 字幕轨，intake 后 `tracks=0`（只接了平台字幕）
- 修复：intake 走「平台字幕 → 内嵌字幕」回退链，调用 `extract_embedded_subtitles` 并入库

---

## 四、并行开发说明

S3 的 4 个子模块由 3 条工作流并行完成：
- 主线：DB 层 + 入库编排 + API（我）
- Agent A：完整性服务（S3-02/03/08）
- Agent B：字幕解析与内嵌提取（S3-04/05/06/07）

三个工作流**互不改对方文件**，接口以 `INTERFACE_CONTRACTS.md` 为准，合并后 57 测试全绿、零冲突。

两个 Agent 的实测校准（已采纳）：
- MKV 流级 duration=None → 退化用容器时长，不判异常
- 无音轨降级限定在 `purpose="asr"`（playback 仍 verified）
- 完整解码判定加严为 rc≠0 或 stderr 非空

---

## 五、S3 Gate 判定

| Gate 条件 | 结果 |
|---|---|
| 四张核心表 + 外键 + 迁移 | ✅ |
| 媒体资产入库（sha 去重） | ✅ |
| 多指标完整性判定 | ✅（5 指标） |
| 内嵌字幕提取（subrip 等） | ✅ |
| 用户字幕导入（SRT/VTT/ASS 解析） | ✅ |
| 平台字幕标准化（秒→毫秒） | ✅ |
| 字幕覆盖率/完整性 | ✅ |
| 多轨并存不覆盖 + 主轨优先级 | ✅ |
| 状态流转落库 | ✅ |

**S3 通过，可进入 S4（本地 ASR）。**

---

## 六、移交 S4 的事项

1. `apps/core/asr.py` 已建（FFmpeg 16k PCM + 切片重叠 + 合并去重 + 时间戳校验），S4 需接 API 并实测。
2. ASR 结果应作为 `source_type="asr"` 的 source_captions 入库（CaptionIntake 已支持）。
3. 模型首次加载慢（S0 实测 600s），S4 需预置模型 + 加载提示。
4. 字幕语义校验（与标题比对的文本级校验）仍待做，可作为 S5 选题。
