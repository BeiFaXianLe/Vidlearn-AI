# 字幕链路说明（平台 → 内嵌 → ASR）

> VidLearn AI V2.0 · 实现于 S3/S4 · 2026-11-02

## 一、三级回退（PRD §4.3）

```
导入/处理视频
   ↓
① 平台字幕      B站登录态：/x/player/v2 → subtitle.subtitles
   │             强校验：末条 ≤ 视频时长+2s、覆盖率 ≥50%、时间戳 snap 到真实字幕点
   │             失败自动重取（最多 3 次），仍失败 → 下一级
   ↓
② 内嵌字幕轨    ffprobe 枚举字幕流 → ffmpeg -map 0:s:<i> 导出 SRT
   │             支持 subrip/mov_text 等；MP4 入库时已转 mov_text 保留
   ↓
③ 本地 ASR      FFmpeg 提取 16kHz 单声道 PCM → faster-whisper（CPU int8）
                 重叠切片 30s/重叠 2s → 逐片识别 → 合并去重 → 时间戳校验
   ↓
④ 云端 ASR      预留扩展（S4-07），默认不启用
```

**导入时默认自动执行 ①→②→③**（`auto_asr=true`）。可在导入弹窗取消勾选。

## 二、为什么 B 站常常走不到 ①

实测结论（S0 证据）：
- 匿名访问：`subtitles = {}`，**平台字幕为空**
- 登录态：可拿到 `ai-zh`（AI 字幕），但**取决于 UP 主是否开启该视频的字幕**
- 因此很多视频最终只能靠 ②/③

## 三、耗时参考（CPU，small 模型，int8）

| 音频时长 | ASR 耗时 | RTF |
|---|---|---|
| 18.5s | 2.5s | 0.19 |
| 74s | 14.3s | 0.19 |
| 180s | 36s | 0.19 |
| 30min（约 1832s） | 约 6min | 约 0.20 |

→ 长视频建议后台跑，界面会显示阶段与进度。

## 四、ASR 相关接口

| 接口 | 说明 |
|---|---|
| `POST /api/asr` | 提交 ASR 任务，立即返回 `task_id`（不阻塞） |
| `GET /api/tasks/{id}` | 查询进度：stage / progress / status / result |
| `GET /api/asr/status` | 模型配置与是否已预置（`model_ready`） |

## 五、已知的字幕质量问题与对策

| 问题 | 对策 |
|---|---|
| B站平台字幕**返回错位内容**（同一 cid 返回 55/138/173 条，含超时长） | 时长校验 + 覆盖率校验 + 重取；仍异常则降级到 ASR |
| 切片硬切导致句子截断/重复 | 重叠 2s + 边界文本去重 + 时间轴裁剪（`_fix_overlaps`） |
| 模型首次加载 600s | 模型预置在 `models/`，`run.ps1` 自动识别 |
| ASR 文本质量 | small 模型中文可用；追求更高精度可换 medium/large（见 MODEL_SETUP） |

## 六、字幕来源的优先级与存储

| source_type | 含义 | 是否 AI 生成 |
|---|---|---|
| `bilibili_human` | 平台人工字幕 | 否 |
| `bilibili_ai` | 平台 AI 字幕 | 是 |
| `embedded` | 视频内嵌字幕轨 | 否 |
| `user` | 用户上传字幕 | 否 |
| `asr` | 本地语音识别 | 是 |

多轨并存不覆盖；主字幕按 `bilibili_human > bilibili_ai > user > embedded > asr` 选择。
