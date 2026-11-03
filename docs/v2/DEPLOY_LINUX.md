# Linux 部署方案（DEPLOY_LINUX）

> VidLearn AI V2.0 · 从 Windows 移植到 Linux 的完整部署指南
> 适用：Ubuntu 22.04+/Debian 12+、CentOS/RHEL 9+、以及 Docker

---

## 1. 移植要点：Windows → Linux 差异

| 能力 | Windows 实现 | Linux 实现（本次已支持） |
|---|---|---|
| Cookie 加密 | DPAPI（绑定 Windows 账户） | **Fernet**（`cryptography`，密钥文件 `.secret.key` 权限 0600） |
| 凭证文件权限 | `icacls` 仅当前用户 | `chmod 600` |
| 启动脚本 | `run.ps1` / `setup.ps1` / `.cmd` | `deploy/setup.sh` / `deploy/run.sh` |
| FFmpeg / yt-dlp | `.exe` | PATH 中的 `ffmpeg` / `ffprobe` / `yt-dlp` |
| 服务托管 | 手动 run.cmd | **systemd**（`deploy/vidlearn.service`） |
| 进程/子进程 | 参数数组调用（无 shell） | 相同，代码已跨平台 |

> **重要**：Windows 下用 DPAPI 加密的 `data/credentials/*.cred` **无法在 Linux 解密**（DPAPI 绑定 Windows 用户）。
> 迁移后需要**重新粘贴一次 B 站 Cookie**（登录一次即可）。其余数据（数据库、媒体、字幕、模型）可直接复用。

---

## 2. 系统要求

| 项 | 建议 |
|---|---|
| CPU | 2 核以上（ASR 主要吃 CPU；4 核更快） |
| 内存 | 4 GB 起；长视频转码/ASR 建议 8 GB |
| 磁盘 | 按视频量估算，建议 ≥100 GB；media 目录独立挂盘更佳 |
| Python | **3.12**（`python3.12`） |
| 系统包 | `ffmpeg`、`curl`、`ca-certificates`、`build-essential`(可选) |
| 外部工具 | `yt-dlp`（固定版本） |
| 前端构建 | Node 18+ / pnpm（仅构建时需要） |

安装系统依赖（Ubuntu/Debian）：

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv ffmpeg curl git
# yt-dlp（二选一）
sudo pipx install yt-dlp        # 或： python3 -m pip install --user yt-dlp
# 或使用官方二进制： https://github.com/yt-dlp/yt-dlp/releases
```

---

## 3. 安装（裸机）

```bash
sudo mkdir -p /opt/vidlearn && sudo chown $USER /opt/vidlearn
git clone <你的仓库地址> /opt/vidlearn
cd /opt/vidlearn

# 一键安装：建 venv、装依赖、构建前端、检查工具
bash deploy/setup.sh

# 配置（填 LLM Key；Cookie 在网页里粘贴，不写文件）
cp .env.example .env && nano .env
```

启动：

```bash
bash deploy/run.sh
# 打开 http://127.0.0.1:8000
```

### 3.1 环境变量（`.env`）

| 变量 | 说明 |
|---|---|
| `VIDLEARN_DATA_ROOT` | 数据根目录（默认 `./data`，生产建议 `/var/lib/vidlearn`） |
| `VIDLEARN_PORT` | 端口（默认 8000） |
| `VIDLEARN_LLM_API_KEY` / `_BASE_URL` / `_MODEL` | 云端 LLM |
| `VIDLEARN_ASR_MODEL_DIR` | 模型目录（`/opt/vidlearn/models/faster-whisper-small`） |
| `VIDLEARN_FFMPEG_PATH` / `_FFPROBE_PATH` / `_YT_DLP_PATH` | 工具路径（默认走 PATH） |

---

## 4. 以 systemd 常驻运行

```bash
sudo useradd -r -s /usr/sbin/nologin vidlearn
sudo mkdir -p /opt/vidlearn/data && sudo chown -R vidlearn:vidlearn /opt/vidlearn

sudo cp deploy/vidlearn.service /etc/systemd/system/vidlearn.service
sudo nano /etc/systemd/system/vidlearn.service   # 确认 WorkingDirectory / User / 路径
sudo systemctl daemon-reload
sudo systemctl enable --now vidlearn
sudo systemctl status vidlearn
journalctl -u vidlearn -f          # 看日志
```

> **必须单进程**：本项目用 SQLite 单连接 + 进程内任务表，`--workers` 只能为 1。
> `run.sh` 已强制；systemd 单元里也是单 worker。

---

## 5. Docker 部署（推荐用于隔离）

```bash
cd deploy
cp ../.env.example ../.env && nano ../.env     # 填 Key
# 把模型放到 ../models/faster-whisper-small（见 MODEL_SETUP.md）
docker compose up -d --build
docker compose logs -f
```

- 镜像内已含 FFmpeg 与固定版本 yt-dlp
- `data/` 与 `models/` 通过 volume 挂载，容器重建不丢数据
- 默认只监听 `127.0.0.1:8000`，对外请用 Nginx 反代

---

## 6. Nginx + HTTPS（可选但推荐）

```bash
sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/vidlearn
sudo ln -s /etc/nginx/sites-available/vidlearn /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
# 证书：sudo certbot --nginx -d vidlearn.example.com
```

**关键点（配置里已写）**：
- `client_max_body_size 8G`：本地大视频上传
- `/api/videos/*/qa` **关闭 proxy_buffering**：否则 SSE 流式问答会被缓冲成一整段
- `/api/videos/*/media` 关闭缓冲 + 透传 `Range`：视频拖动
- 长超时：下载/ASR/分析可能数分钟

---

## 7. 数据迁移（从 Windows 迁移）

```bash
# 1) 拷贝数据（数据库、媒体、字幕、总结、收藏夹）
rsync -av "/path/win/data/" /opt/vidlearn/data/

# 2) 拷贝模型（可选，避免重新下载）
rsync -av "/path/win/models/" /opt/vidlearn/models/

# 3) 凭证：DPAPI 密文在 Linux 无效，删除后重新登录
rm -f /opt/vidlearn/data/credentials/*.cred
# 启动后在“导入视频”里重新粘贴一次 SESSDATA

# 4) 修复权限
sudo chown -R vidlearn:vidlearn /opt/vidlearn/data /opt/vidlearn/models
```

> SQLite 数据库跨平台兼容，直接拷贝 `data/database/vidlearn.db` 即可；
> 若启用了 WAL，建议在 Windows 端先正常退出服务再拷贝（或同时拷 `-wal`/`-shm`）。

---

## 8. 磁盘与存储

- 视频会占大量空间：建议把 `VIDLEARN_DATA_ROOT` 指到独立磁盘（如 `/data/vidlearn`）
- 首页有磁盘容量/告警阈值；服务端阈值存在 `app_settings` 表
- 定期清理：`python scripts/maintain_media.py`
- 可用 `systemd` 的 `MemoryMax` 限制内存；磁盘配额可用 `quota` 或独立分区

```bash
# 例：把数据迁到独立盘
sudo mkdir -p /data/vidlearn && sudo mount /dev/sdb1 /data/vidlearn
# .env: VIDLEARN_DATA_ROOT=/data/vidlearn
```

---

## 9. 性能与安全

| 项 | 建议 |
|---|---|
| ASR | CPU int8 单进程；RTF≈0.2（30 分钟视频约 6 分钟）。多核可调 `OMP_NUM_THREADS` |
| 并发导入 | 后台任务串行执行；不要开多 worker |
| 运行用户 | 非 root（systemd `User=vidlearn` / Docker `uid 10001`） |
| 凭证 | Fernet 密钥 `data/credentials/.secret.key`（0600），**不要提交/外传** |
| 网络 | 默认只监听 127.0.0.1；对外用 Nginx + HTTPS + 防火墙 |
| 子进程 | yt-dlp/FFmpeg 参数数组调用，无 shell 拼接 |
| 合规 | 仅处理有权获取的内容；不绕过 DRM/会员/验证码/反爬 |

SELinux（CentOS/RHEL）若拦截，允许服务写数据目录：

```bash
sudo semanage fcontext -a -t httpd_sys_rw_content_t "/opt/vidlearn/data(/.*)?"
sudo restorecon -Rv /opt/vidlearn/data
```

---

## 10. 故障排查

| 现象 | 排查 |
|---|---|
| 启动报 `ffmpeg not found` | `apt install ffmpeg`；或设 `VIDLEARN_FFMPEG_PATH` |
| B 站下载失败 `need_login` | 重新粘贴 Cookie（迁移后必须重登） |
| 中文日志乱码 | `run.sh` 已设 `PYTHONUTF8=1`；systemd 单元也设了 |
| 问答不是流式（一次性出现） | Nginx 未关闭 `proxy_buffering`（见第 6 节） |
| 视频不能拖动 | 反代未透传 `Range` 头 |
| 模型下载慢/失败 | 用镜像下载，见 `docs/v2/MODEL_SETUP.md`；或手动放 `models/` |
| 磁盘告警导致导入被拦截 | 首页点阈值按钮调整，或清理旧视频 |
| 权限错误（data 写不进） | `chown -R vidlearn:vidlearn data`；SELinux 见第 9 节 |

---

## 11. 备份 / 升级 / 卸载

```bash
# 备份（停服后拷数据目录最稳）
sudo systemctl stop vidlearn
tar czf vidlearn-backup-$(date +%F).tar.gz -C /opt/vidlearn data
sudo systemctl start vidlearn

# 升级
cd /opt/vidlearn && git pull
bash deploy/setup.sh          # 装新依赖 + 重建前端
sudo systemctl restart vidlearn

# 卸载（保留数据则跳过 rm data）
sudo systemctl disable --now vidlearn
sudo rm /etc/systemd/system/vidlearn.service
sudo rm -rf /opt/vidlearn
```

---

## 12. 与 Windows 版的功能差异

- 功能完全一致（导入/字幕/ASR/AI/问答/收藏/磁盘/批量），**抖音仍暂缓**
- 凭证加密实现不同（DPAPI ↔ Fernet），但接口一致，前端无感
- FFmpeg 许可证与 Windows 相同：对外分发注意 GPL（见 `LICENSE_AUDIT.md`）
