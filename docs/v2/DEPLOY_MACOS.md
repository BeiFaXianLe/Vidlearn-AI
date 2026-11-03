# macOS 部署方案（DEPLOY_MACOS）

> VidLearn AI V2.0 · macOS 支持说明与部署指南
> 适用：macOS 13+（Intel / Apple Silicon）

## 1. 支持状态：**原生支持**

代码层已跨平台，macOS 与 Linux 走同一套 POSIX 路径，**无需改代码**：

| 能力 | macOS 实现 |
|---|---|
| Cookie/凭证加密 | **Fernet**（`cryptography`），密钥 `data/credentials/.secret.key`，权限 `600` |
| 文件权限 | `chmod 600` |
| 媒体处理 | Homebrew `ffmpeg`（含 ffprobe） |
| 下载器 | `yt-dlp`（pip/uv/brew） |
| 前端构建 | Node + pnpm（corepack） |
| 常驻服务 | **launchd**（`deploy/com.vidlearn.ai.plist`） |
| 容器 | Docker Desktop for Mac |

> 与 Linux 唯一区别是**服务托管方式**：Linux 用 systemd，macOS 用 launchd。

---

## 2. 环境准备

```bash
# 1) Homebrew（如未安装）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2) 依赖
brew install python@3.12 ffmpeg git
brew install yt-dlp            # 或： pipx install yt-dlp

# 3) Node（用于构建前端，仅首次需要）
brew install node pnpm
```

Apple Silicon 提示：`brew` 默认装在 `/opt/homebrew`，`python3.12` 路径通常是
`/opt/homebrew/bin/python3.12`；Intel 在 `/usr/local/bin/python3.12`。

---

## 3. 安装与启动

```bash
sudo mkdir -p /opt/vidlearn && sudo chown "$USER" /opt/vidlearn
git clone <你的仓库地址> /opt/vidlearn
cd /opt/vidlearn

bash deploy/setup.sh          # 建 venv、装依赖、构建前端、检查工具
cp .env.example .env && open -e .env    # 填 VIDLEARN_LLM_API_KEY

bash deploy/run.sh            # 前台启动 http://127.0.0.1:8000
```

> 若 `python3.12` 不在 PATH：`PYTHON=/opt/homebrew/bin/python3.12 bash deploy/setup.sh`

---

## 4. 常驻运行（launchd）

```bash
mkdir -p ~/Library/LaunchAgents
cp deploy/com.vidlearn.ai.plist ~/Library/LaunchAgents/
# 按实际路径修改 plist 里的 ProgramArguments / WorkingDirectory（默认 /opt/vidlearn）
open -e ~/Library/LaunchAgents/com.vidlearn.ai.plist

launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.vidlearn.ai.plist
launchctl kickstart -k gui/$(id -u)/com.vidlearn.ai     # 立即启动
launchctl print gui/$(id -u)/com.vidlearn.ai            # 查看状态
tail -f /opt/vidlearn/data/logs/launchd.out.log         # 日志
```

停止 / 卸载：

```bash
launchctl bootout gui/$(id -u)/com.vidlearn.ai
rm ~/Library/LaunchAgents/com.vidlearn.ai.plist
```

> LaunchAgent 在**用户登录后**启动；若需开机即启动（无需登录），放到
> `/Library/LaunchDaemons/` 并用 `sudo launchctl bootstrap system ...`。
> 仍然**只能单 worker**（SQLite + 进程内任务表）。

---

## 5. Docker（可选）

```bash
open -a Docker          # 启动 Docker Desktop
cd deploy
cp ../.env.example ../.env && open -e ../.env
docker compose up -d --build
```

---

## 6. macOS 常见问题

| 现象 | 解决 |
|---|---|
| `python3.12: command not found` | `brew install python@3.12`，或 `PYTHON=/opt/homebrew/bin/python3.12` |
| `ffmpeg not found` | `brew install ffmpeg`；确认 `which ffmpeg` |
| 首次运行被 Gatekeeper 拦截 | 仅对下载的二进制有效；本项目为源码运行，一般无此问题 |
| 端口被占用 | `PORT=8010 bash deploy/run.sh` |
| 视频无法本地播放（编码不支持） | 已自动把 MKV/MOV 转 MP4；HEVC 请用支持该编码的浏览器或转 H.264 |
| 想让局域网访问 | `HOST=0.0.0.0 bash deploy/run.sh`，并在“系统设置→网络→防火墙”放行 |
| 休眠后任务中断 | launchd 会重启进程；任务状态可能标记失败，可点“重试” |
| 模型下载慢 | 用镜像，见 `docs/v2/MODEL_SETUP.md` |

**Apple Silicon 说明**：`faster-whisper`/`ctranslate2` 提供 arm64 轮子，CPU 推理可用（RTF≈0.2）。
如需 GPU 加速，可自行安装支持 Metal 的引擎（非本项目默认路径）。

---

## 7. 从 Windows / Linux 迁移到 macOS

```bash
rsync -av "/原系统/data/"   /opt/vidlearn/data/
rsync -av "/原系统/models/" /opt/vidlearn/models/
rm -f /opt/vidlearn/data/credentials/*.cred     # DPAPI/Fernet 密文不可跨机解密
chmod -R u+rwX /opt/vidlearn/data
# 启动后重新粘贴一次 B 站 Cookie
```

> 数据库（SQLite）与媒体文件跨平台兼容，可直接复用。

---

## 8. 三平台对照

| 项 | Windows | Linux | macOS |
|---|---|---|---|
| 启动脚本 | `setup.cmd` / `run.cmd` | `deploy/*.sh` | `deploy/*.sh` |
| 凭证加密 | DPAPI | Fernet | **Fernet** |
| 常驻服务 | 手动/计划任务 | systemd | **launchd** |
| 容器 | Docker Desktop | Docker | Docker Desktop |
| 单 worker 限制 | 是 | 是 | 是 |
| 功能 | 全量（抖音暂缓） | 全量 | 全量 |

详见 Linux 指南：[DEPLOY_LINUX.md](DEPLOY_LINUX.md)
