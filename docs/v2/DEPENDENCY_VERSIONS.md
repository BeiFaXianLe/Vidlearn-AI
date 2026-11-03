# 依赖版本清单（DEPENDENCY_VERSIONS）

> VidLearn AI V2.0 · S0 冻结基线
> 原则：所有外部工具与库**固定版本**，升级前跑回归样本。

## 一、运行时与工具（生产必须一致）

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | **3.12.x**（实测 3.12.13） | 用 `uv` 管理；**不要用系统默认 3.14**（ML 轮子不成熟） |
| uv | 0.11.x（实测 0.11.29） | Python/依赖管理 |
| **yt-dlp** | **2026.10.26** | 下载器，需固定版本并在升级前回归 |
| **FFmpeg / FFprobe** | **8.1.1**（gyan.dev full_build） | ⚠️ full build 含 GPL 组件；**对外分发需换 LGPL build** |
| faster-whisper | 1.2.1 | 本地 ASR，CPU int8 |
| ctranslate2 | 随 faster-whisper | 推理后端 |
| Node.js | 24.x（实测 24.15.0） | 前端构建 |
| pnpm | 11.x（实测 11.10.0） | 前端包管理 |
| Docker | 29.5.2（可选） | 仅抖音/辅助服务需要；本期不依赖 |

## 二、Python 依赖（后端）

| 库 | 版本约束 | 用途 |
|---|---|---|
| fastapi | ≥0.115 | Web API |
| uvicorn[standard] | ≥0.54 | ASGI 服务 |
| pydantic | ≥2.9 | 数据模型 |
| python-multipart | 最新 | 文件上传 |
| faster-whisper | ==1.2.1 | ASR |
| pyyaml | ≥6.0 | 配置 |
| httpx | ≥0.25 | 出站 HTTP（抖音/ASR/LLM） |
| sqlite-utils / 迁移工具 | 待 S1 定 | 数据访问 |

## 三、ASR 模型

| 模型 | 大小 | 说明 |
|---|---|---|
| Systran/faster-whisper-small | ~460MB | 默认（CPU int8，RTF≈0.19） |
| medium / large-v3 | 更大 | 可选升级，需验证 RTF 与内存 |

⚠️ **模型必须预置或启动时预下载**。首次从 HF 下载实测耗时 **600 秒**，不可作为用户首次体验。

## 四、已知版本兼容问题

| 问题 | 处理 |
|---|---|
| faster-whisper 1.2.1 与 **PyAV 19** 不兼容（`metadata_errors` 参数） | **不使用 PyAV**；音频统一由 FFmpeg 解 16k PCM 后以 numpy 输入 |
| HF 缓存符号链接在 Windows 不可用（占更多磁盘） | 设 `HF_HUB_DISABLE_SYMLINKS_WARNING=1`；规划磁盘配额 |
| `curl.exe` 在本机不可用（SSL error 35） | 所有网络验证用 Python/yt-dlp，不用 curl 判断连通性 |

## 五、许可证备注

| 组件 | 许可证 | 分发影响 |
|---|---|---|
| yt-dlp | Unlicense | 宽松 |
| FFmpeg full build | GPLv3（含 x264 等） | **对外分发需合规评估或换 LGPL build** |
| faster-whisper | MIT | 宽松 |
| jiji262/douyin-downloader | MIT | 宽松（本期暂缓接入） |
| Evil0ctal/Douyin_TikTok_Download_API | Apache-2.0 | 宽松（备用） |
