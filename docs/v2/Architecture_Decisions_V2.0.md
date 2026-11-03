# VidLearn AI · Architecture Decisions V2.0

> 版本：V2.0 · 2026-11-02
> 说明：本文档整理自 V2.0 冻结正文（PRD / Development Plan）。标注 **[冻结]** 的为原文明确决策；标注 **[推导]** 的为从冻结内容直接推导出的落地约定，需在 S0 结束后确认。

## 1. 冻结决策（D01–D05）[冻结]

| 编号 | 决策 | 方案 |
|---|---|---|
| D01 | Cookie 加密 | Windows DPAPI |
| D02 | B站登录 | 用户手动粘贴 Cookie，系统负责格式转换、加密和管理 |
| D03 | 抖音下载 | `jiji262/douyin-downloader`，独立 Python 子进程 |
| D04 | 抖音 Cookie | 不预设必须登录，先验证匿名下载能力 |
| D05 | 抖音 PoC | 正式开发前必须完成技术验证，不通过不得标记正式可用 |

## 2. 继承的产品决策 [冻结]

| 项目 | 决策 |
|---|---|
| ASR | 本地 faster-whisper 默认 |
| 视频保留 | 永久保留，用户手动删除 |
| 首发平台 | Windows |
| 云端 AI 数据边界 | 仅上传字幕、文本；不上传视频、音频、关键帧 |
| B站清晰度 | 登录态优先 1080P；匿名按 720P 设计 |
| 字幕优先级 | 平台字幕 → 内嵌字幕 → 本地 ASR（云端 ASR 为可选扩展） |
| 视频处理 | 下载到本地后处理、本地播放 |
| 原型 | 保留现有原型和核心学习工作台 |

## 3. 技术栈基线 [冻结]

- 前端：React（保留现有原型视觉与交互）
- 数据库：沿用现有技术栈，非必要不引入新数据库
- 媒体处理：FFmpeg / FFprobe（外部子进程）
- ASR：faster-whisper 本地 CPU int8
- 视频编码：优先 H.264
- 开发环境：Python 3.12 + uv

## 4. 模块边界 [冻结]

```
业务服务层
├── TaskManager          任务调度与状态机
├── VideoAdapter         统一来源接口
│   ├── BilibiliAdapter  匿名 / 登录双模式
│   ├── DouyinAdapter    独立 Python 子进程
│   └── LocalFileAdapter 本地文件
├── MediaProcessor       FFmpeg / FFprobe 封装
├── TranscriptService    平台字幕 / 内嵌字幕 / ASR
└── AIAnalysisService    LLM Provider
```

## 5. 接口与运行时约定

### 5.1 Provider / Adapter 抽象 [冻结]
下载器、ASR、LLM 一律通过 Provider/Adapter 抽象，便于替换实现。

### 5.2 凭证运行时 [冻结]
- 存储：Windows DPAPI 加密
- 使用：仅本地下载流程，不向 AI 或外部服务提供 Cookie
- 日志：不得输出 Cookie；异常堆栈与调试日志同样脱敏
- 不入代码仓库、不入普通临时文件
- 支持更新、清除、失效检测

### 5.3 抖音子进程隔离 [冻结]
- 独立 Python 子进程，与主业务进程隔离
- 主程序通过 stdin/stdout 或约定协议获取结果
- 失败返回明确错误码
- 子进程异常不得影响主程序（S8-02）

### 5.4 音频处理路径 [冻结]
**不使用 PyAV 作为音频处理核心路径**；统一走 FFmpeg 提取 16kHz 单声道 PCM。
（该决策来自 S0 实测：faster-whisper 1.2.1 与 PyAV 19 的 `metadata_errors` 参数不兼容。）

## 6. 数据与状态模型 [冻结]

核心表：`media_assets`、`source_captions`、`transcript_segments`

媒体完整性状态：`verified` / `likely` / `partial` / `unknown`

任务状态机：

```
CREATED → MEDIA_PROCESSING → MEDIA_READY
→ TRANSCRIPT_PROCESSING → TRANSCRIPT_READY
→ AI_ANALYZING → COMPLETED / FAILED
```

## 7. 待 S0 后确认 [推导]

1. B站下载参数与格式选择策略（`bv*+ba` 的具体 selector）
2. 平台字幕 JSON 字段与秒→毫秒转换细节
3. 抖音下载器子进程通信协议的具体格式（JSON Lines / 临时目录）
4. 完整性判定的阈值（时长容差、尾部解码窗口）
5. LLM Provider 首选供应商与结构化输出 Schema
6. 数据库迁移工具选型（沿用现有）
