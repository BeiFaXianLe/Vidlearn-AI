# V2 增强功能（磁盘 / 批量导入 / 收藏 / 任务控制 / 问答）

> 对齐原型 V1.1（2026-11-02）· 全部已实现并实测

## 1. 磁盘容量与占用统计

| 接口 | 说明 |
|---|---|
| `GET /api/storage` | 磁盘总量/已用/剩余、使用率、阈值、是否告警、分类占用、Top5 视频 |
| `PUT /api/storage/threshold` | 设置告警阈值（50–99%，越界自动夹紧） |

- 容量来自 `shutil.disk_usage(data_root)`（真实分区）
- **分类占用**：视频文件 / 字幕与转写 / AI 总结与索引 / 缩略图与其他（由媒体表与文本长度估算）
- **Top5 占用最多的视频**（可点击进入详情）
- 阈值告警：`warn`（≥阈值）、`danger`（≥95%）
- 视频列表接口返回 `size_bytes`，卡片显示单个视频占用

## 2. 批量导入（后台执行）

| 接口 | 说明 |
|---|---|
| `POST /api/intake/batch` | body: `{sources:[...], max_height?, auto_asr?, auto_punctuate?, allow_over_threshold?}` |

- 每行一个链接/本地路径，单次最多 **20** 条
- 每个来源创建一个**独立后台任务**，立即返回 `task_ids`，可离开页面
- **容量阈值拦截**：使用率超阈值时返回 `409`，前端提示后可选择「强制导入」
- 实测：同一文件并发导入 3 次，全部成功（临时目录已加唯一后缀，避免并发冲突）

## 2.1 从 B站收藏夹导入（登录态）

| 接口 | 说明 |
|---|---|
| `GET /api/bilibili/fav/folders` | 读取当前登录账号的收藏夹列表：`{mid, uname, folders:[{id,title,count}]}` |
| `GET /api/bilibili/fav/items?media_id=&page=&page_size=` | 分页读取收藏夹内视频：`{items:[{bvid,title,author,duration_s}], has_more, count}` |

- 需先在导入弹窗粘贴含 `SESSDATA` 的 B站 Cookie（DPAPI 加密保存，不落明文）
- 未登录 / Cookie 失效 → 返回 `ok:false, error.code=need_login`
- 前端：点「读取我的收藏夹」→ 选文件夹 → 勾选视频 → 「导入选中」，复用 `/api/intake/batch` 后台队列（单次仍限 20 条，超出请分批）
- 已失效视频（无 bvid）自动跳过

## 3. 收藏夹

| 接口 | 说明 |
|---|---|
| `POST /api/videos/{id}/favorite` | body: `{favorite: true/false}` |
| `GET /api/favorites/count` | 收藏数量（侧边栏红点数字） |
| `GET /api/videos?favorite=1` | 只看收藏 |

- 卡片右上角 ☆/★ 一键收藏；收藏视图隐藏统计卡与磁盘卡（`favmode`）

## 3.1 自定义收藏夹（多收藏夹）

| 接口 | 说明 |
|---|---|
| GET /api/collections | 收藏夹列表（含每个夹的视频数） |
| POST /api/collections | 新建 {name, color?}（重名返回已有） |
| PATCH /api/collections/{id} | 重命名 {name}（重名 400） |
| DELETE /api/collections/{id} | 删除收藏夹（**视频本身不删除**） |
| GET /api/videos/{id}/collections | 该视频所属收藏夹 |
| PUT /api/videos/{id}/collections | 整体设置归属 {collection_ids:[...]} |
| POST /api/videos/{id}/collections/{cid}/toggle | 加入/移出某个收藏夹 |

- 多对多：一个视频可属于多个收藏夹
- 卡片 ☆ 打开选择器，可勾选多个收藏夹、就地新建
- 收藏视图顶部 chip：全部收藏 + 每个收藏夹（可重命名 ✎ / 删除 ×）+ ＋新建收藏夹
- 旧接口 avorite=true/false 兼容：收藏→加入「默认收藏」，取消→清空所有归属
- 删除收藏夹不影响视频文件与知识资产

## 4. 任务控制（暂停 / 继续 / 重试 / 取消）

| 接口 | 说明 |
|---|---|
| `POST /api/tasks/{id}/pause` | 暂停（在阶段边界生效） |
| `POST /api/tasks/{id}/resume` | 继续 |
| `POST /api/tasks/{id}/cancel` | 取消（阶段边界抛出，任务标记 cancelled） |
| `POST /api/tasks/{id}/retry` | 用原参数重新执行 |

实现：`JobStore` 增加 `control`（running/paused/cancelled）与 `payload`（供重试）；
pipeline 在每个阶段开始前调用 `_checkpoint()` —— 暂停时等待，取消时终止。
> 说明：暂停/取消在**阶段边界**生效（正在执行的 yt-dlp/ASR 子进程不会被强杀）。

## 5. 视频问答（流式输出 + 时间点引用）

| 接口 | 说明 |
|---|---|
| `POST /api/videos/{id}/qa` | body: `{question, caption_id?}`，返回 **SSE** 流 |

- 只把**字幕文本**发给 LLM（遵循数据边界）
- 上下文构建：按问题关键词粗筛相关字幕段 + 首尾背景，限制在 ~24k 字符
- 提示词要求回答用 `【mm:ss】` 标注引用
- 流式事件：`data:{"delta":"..."}` 多次 → `data:{"done":true,"citations":[...]}`
- 前端打字机效果（`typing-cursor`），`【mm:ss】` 渲染为**可点击时间点**，点击跳转播放器
- 无字幕时明确提示不可用

### 实测（30 分钟 B站视频）
```
HTTP 200  text/event-stream
收到增量块 209 | 提取引用 14 个（00:14, 07:44, 07:47 …）
```

## 6. UI 对齐（原型 V1.1）

- 首页：4 统计卡 → **磁盘容量双卡**（容量条+图例 / Top5）→ **后台任务面板** → 视频网格
- 侧边栏：视频首页 / **我的收藏（计数）** / 我的知识库 / 学习记录 / 设置
- 卡片：右上 ★收藏 + hover 删除（删除按钮已修 `pointer-events`，不再遮挡点击）
- 详情 Tabs：**AI 总结 / 章节与字幕 / AI 问答 / 笔记**（知识点并入「笔记」Tab）
- 播放器 sticky 吸顶

## 7. 已知限制

1. 删除/暂停在阶段边界生效，无法中断正在进行的下载或 ASR。
2. 磁盘分类中的「AI 总结与索引」「缩略图」为估算值。
3. 问答上下文做了粗筛，超长视频可能遗漏细节（后续可做向量检索，V1.3）。
4. 批量导入为串行排队执行（并发数受限于磁盘与网络）。
