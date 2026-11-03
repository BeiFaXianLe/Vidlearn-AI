# VidLearn AI

以本地媒体库为基础的个人视频学习工作站：把 B 站视频或本地视频，转成可播放、可检索、可复习的知识资产。

- **版本**：V2.0（决策已冻结）
- **平台**：Windows First
- **技术栈**：FastAPI + SQLite + React/TypeScript/Vite + yt-dlp + FFmpeg + faster-whisper

---

## 1. 快速开始

```powershell
# 首次：安装（创建 .venv、装依赖、构建前端）
setup.cmd            # 双击，或在 PowerShell 里：powershell -ExecutionPolicy Bypass -File .\setup.ps1

# 启动
run.cmd             # 双击；默认 http://127.0.0.1:8000
```

### 前置依赖

| 依赖 | 版本 | 说明 |
|---|---|---|
| Python | **3.12**（3.14 太新，部分 ML 轮子不支持） | 运行后端 |
| [uv](https://docs.astral.sh/uv/) | 最新 | 建虚拟环境/装依赖（可选，setup 会自动回退 pip） |
| FFmpeg / FFprobe | 5.0+ | 媒体探测、转码、抽音频（需在 PATH） |
| yt-dlp | 2026.10+ | 下载器（`uv tool install yt-dlp`） |
| Node.js + pnpm | Node 18+ / pnpm 8+ | 构建前端（仅首次构建需要） |

> setup.cmd 会检查并提示缺失项。也可手动 `uv sync` 后 `.venv\Scripts\python -m uvicorn apps.main:app`。

> PowerShell 提示"未数字签名"是执行策略限制，用 `setup.cmd` / `run.cmd` 即可绕过，无需改系统策略。

**Linux / macOS：**

```bash
bash deploy/setup.sh      # 建 venv、装依赖、构建前端
bash deploy/run.sh        # 默认 http://127.0.0.1:8000
```

也支持 **systemd 常驻**与 **Docker**，以及 Nginx（含 SSE 流式/视频 Range 配置）：
见 [docs/v2/DEPLOY_LINUX.md](docs/v2/DEPLOY_LINUX.md)。

---

## 2. 目录结构（代码 / 数据 / 模型 分离）

```
VidLearn AI/
├── apps/                  ← 【代码】后端应用（Python）
│   ├── main.py            FastAPI 入口、路由注册、静态前端托管
│   ├── api_s2~s7.py      各阶段 REST API（获取/入库/ASR/AI/播放/库）
│   ├── api_s5_punct.py   字幕标点恢复
│   ├── api_s6_media.py   HTTP Range 媒体播放
│   ├── api_v2_ext.py     磁盘/收藏夹/批量导入/任务控制/问答
│   ├── core/              业务核心：配置/凭证/任务/完整性/字幕/ASR/AI/入库
│   ├── adapters/          视频来源适配器（B站 / 本地文件）
│   ├── storage/           SQLite schema 与数据访问层
│   └── web/               【代码】前端（React + Vite）
│       ├── src/           源码（App.tsx / api.ts / styles.css）
│       └── dist/          构建产物（FastAPI 托管；**未提交**，需 setup 构建）
│
├── data/                  ← 【运行时数据】程序生成，可备份/清空，勿手改
│   ├── database/          SQLite 数据库 vidlearn.db
│   ├── media/original/    已入库的原始媒体（可浏览器播放的 mp4/webm）
│   ├── media/temp/        下载/上传临时区（自动清理）
│   ├── media/audio_work/  ASR 提取的 16k 音频（用完即删）
│   ├── media/subtitles/   提取出的字幕文件
│   ├── media/thumbnails/  封面缩略图
│   ├── media/keyframes/   P1 关键帧
│   ├── exports/           Markdown 等导出
│   ├── logs/              运行日志（已脱敏）
│   └── credentials/       DPAPI 加密的 Cookie（密文）
│
├── models/                ← 【AI 模型】与代码/数据隔离
│   └── faster-whisper-small/   ASR 模型（约 464MB）
│
├── docs/                  ← 【文档】按版本分目录
│   ├── v2/                当前基线 V2.0（PRD/计划/交付报告/evidence）
│   └── v1/                历史 V1.1（交付包 + HTML 原型 + 早期调研）
├── tests/                 ← 【测试】单元测试
│   └── fixtures/media/    测试用媒体样本（非运行时数据）
├── scripts/               ← 【工具】维护脚本（如 maintain_media.py）
├── .venv/                 虚拟环境（安装生成，勿提交）
└── .tmp/                  临时/缓存（可随时删除）
```

### 临时文件与 Cookie 安全

- yt-dlp 需要的 Cookie 文件**只写到** data/media/temp/cookies/（或项目 .tmp/cookies/），
  用完立即删除；**绝不写项目根目录**。
- 服务启动时自动清理残留 Cookie 临时文件与 job_* 临时目录。
- .gitignore 已忽略 data/、.tmp/、cookie_*.txt、/tmp*.txt、.env、*.cred 等。
- 手动维护：.\.venv\Scripts\python.exe scripts\maintain_media.py
  （清孤儿媒体/记录、未引用文件、临时音频、残留 Cookie 文件、临时目录）

**三分原则**：
- **代码** → `apps/`（含前端 `apps/web/src`）
- **运行时数据** → `data/`（视频、数据库、日志、凭证都在这里）
- **模型** → `models/`
- **测试资源** → `tests/fixtures/`（不进 `data/`，避免与真实数据混淆）

---

## 3. 配置（环境变量，前缀 `VIDLEARN_`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `VIDLEARN_DATA_ROOT` | `./data` | 数据根目录 |
| `VIDLEARN_PORT` | 8000 | 服务端口 |
| `VIDLEARN_FFMPEG_PATH` / `VIDLEARN_FFPROBE_PATH` | ffmpeg/ffprobe | 工具路径 |
| `VIDLEARN_YT_DLP_PATH` | yt-dlp | 下载器路径 |
| `VIDLEARN_ASR_MODEL` | small | ASR 模型规格 |
| `VIDLEARN_ASR_MODEL_DIR` | 空 | 自定义模型目录；留空自动找 `./models/faster-whisper-<model>` |
| `VIDLEARN_LLM_API_KEY` | 空 | 云端 LLM 密钥（不入仓库） |
| `VIDLEARN_LLM_BASE_URL` | deepseek | OpenAI 兼容端点 |
| `VIDLEARN_LLM_MODEL` | deepseek-chat | 模型名 |

---

## 4. 功能与使用

1. **导入**：点右上角「导入视频」→ B 站链接或本地文件路径 →（可选）贴 Cookie 获取平台字幕/高清 → 后台任务带进度。
2. **字幕三级回退**（自动）：**平台字幕**（登录态优先）→ **视频内嵌字幕** → **本地 ASR**（faster-whisper，默认开启）。导入时若前两级都没有，会自动跑 ASR 生成字幕；耗时约为音频时长的 1/5（30 分钟视频约 6 分钟，CPU）。
3. **播放**：详情页本地播放器，支持拖动（HTTP Range）；MKV/MOV 入库时自动转 MP4，浏览器可直接播放。
4. **AI 分析**：摘要 / 章节 / 知识点（需配置 LLM Key）。
5. **学习**：章节跳转、笔记、学习进度自动保存、Markdown 导出。
6. **磁盘管理**：容量与分类占用、Top5 大文件、告警阈值（超阈值时新导入会被拦截并提示）。
7. **批量导入**：一次最多 20 条，后台排队执行，支持暂停/继续/重试/取消。
8. **自定义收藏夹**：可建多个命名收藏夹，卡片 ☆ 勾选归属（支持多归属），侧边栏「我的收藏」按收藏夹筛选/重命名/删除。
9. **AI 问答**：基于字幕的流式问答（打字机效果），回答中的时间点可点击跳转。
10. **繁简转换**：字幕入库统一转简体（OpenCC t2s），存量可用 `scripts/simplify_captions.py` 迁移。
11. **字幕分段展示**：逐句字幕按停顿/标点合并成段落显示（库内仍保留细粒度用于精确定位）。
12. **工作台交互**：播放器滚动时吸顶、章节与字幕合并为同一 Tab、点击章节定位字幕块。

> 已有视频想补字幕：详情页「章节与字幕」Tab →「运行本地 ASR 生成字幕」。
> 详细说明见 [docs/v2/V2_FEATURES.md](docs/v2/V2_FEATURES.md)。

**数据模型（SQLite，启动自动迁移）**：`videos` / `media_assets` / `source_captions` / `transcript_segments` /
`summaries` / `chapters` / `knowledge_points` / `notes` / `learning_progress` /
`collections` / `video_collections` / `processing_tasks` / `app_settings`

---

## 5. 测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```
当前共 **167 个单元测试**（含字幕、完整性、ASR、标点、收藏夹、Cookie 安全等）。

维护（清理孤儿媒体、历史临时文件）：
```powershell
.\.venv\Scripts\python.exe scripts\maintain_media.py
```

---

## 6. 重要说明

- **抖音**：暂缓接入（开源 CLI 方案被平台风控阻断），保留 Adapter 接口与降级提示。
- **模型**：已预置 `models/faster-whisper-small/`；换机/重装见 [docs/v2/MODEL_SETUP.md](docs/v2/MODEL_SETUP.md)。
- **许可证**：FFmpeg 为 GPL full build，对外分发前需换 LGPL（见 [docs/v2/LICENSE_AUDIT.md](docs/v2/LICENSE_AUDIT.md)）。
- **字幕标点**：ASR 字幕自动用 LLM 补标点（派生轨，原始字幕保留），见 [docs/v2/PUNCTUATION.md](docs/v2/PUNCTUATION.md)
- **密钥不入库**：.env（含 API Key）、data/（含 DPAPI 加密的 Cookie、日志、数据库）、
  models/、.venv/、.tmp/、jieba.cache 等均已被 .gitignore 排除；仓库只含源码与文档。
  克隆后请复制 .env.example 为 .env 并填入自己的 Key。
- **跨平台**：Windows 用 DPAPI 加密 Cookie，Linux/macOS 用 Fernet（密钥 0600）。
  从 Windows 迁移到 Linux 后需**重新登录一次**（DPAPI 密文不可跨系统解密），见 [DEPLOY_LINUX.md](docs/v2/DEPLOY_LINUX.md)。
- **部署**：Windows 脚本 setup.cmd/run.cmd；Linux deploy/*.sh + systemd + Docker + Nginx 示例。
- **合规**：仅处理你有权获取的内容；不绕过 DRM/会员/验证码/反爬；云端 AI 只接收文本。

---

## 7. 文档索引

文档按版本分目录：
- **当前基线 V2.0** → [docs/v2/README.md](docs/v2/README.md)
  - 需求与计划：[PRD_V2.0.md](docs/v2/PRD_V2.0.md) · [Development_Plan_V2.0.md](docs/v2/Development_Plan_V2.0.md)
  - 阶段交付报告：`docs/v2/S0_…` ~ `docs/v2/S8_DELIVERY_REPORT.md`
- **历史 V1** → [docs/v1/README.md](docs/v1/README.md)（含 V1.1 交付包与 HTML 原型）
- 总索引：[docs/README.md](docs/README.md)

