# S1 交付报告：基础设施与凭证管理

- 日期：2026-11-02
- 状态：**完成**（13 个单元测试通过，FastAPI 启动自检 5/5 通过）
- 依据：PRD V2.0 / Development Plan V2.0 / INTERFACE_CONTRACTS.md / DEPENDENCY_VERSIONS.md

---

## 一、交付物与代码位置

| 任务 | 文件 | 说明 |
|---|---|---|
| S1-01 工程骨架 | `pyproject.toml`、`apps/`、`packages/`、`data/` | Python 3.12 + uv |
| S1-02 配置管理 | `apps/core/config.py` | pydantic-settings，YAML/环境变量覆盖 + 校验 |
| S1-08 媒体目录 | `apps/core/config.py:MediaDirs` | original/temp/audio_work/subtitles/thumbnails/keyframes/exports/database/logs |
| S1-03 CredentialProvider | `apps/core/credentials.py` | 统一接口（set/get/clear/status） |
| S1-04 DPAPI 加密 | `apps/core/credentials.py:_Dpapi` | Windows CryptProtectData；密文落盘 |
| S1-05 Cookie 导入 | `apps/core/credentials.py:parse_cookie` | **含 URL 解码**（S0 关键约束） |
| S1-06 日志脱敏 | `apps/core/logging_setup.py` | RedactingFilter 拦截 SESSDATA/ttwid 等 |
| S1-07 TaskManager | `apps/core/tasks.py` | PRD 状态机 + 流转合法性 |
| 应用入口 | `apps/main.py` | FastAPI + lifespan 自检 + /api/health |
| 测试 | `tests/test_s1.py` | 13 个用例 |

---

## 二、验证结果

### 2.1 单元测试
```
13 passed in 0.22s
```
覆盖：配置默认值 / 媒体目录创建 / 环境自检 / Cookie 解析（URL 编码、完整头、空值）/ 脱敏 /
凭证往返 / 后端报告 / 非法输入 / 任务状态机（正常路径、非法流转、失败重试）。

### 2.2 环境自检（服务启动时）
```
status: ok | env: dev
  OK  python>=3.12,<3.13 -> 3.12.13
  OK  ffmpeg   -> D:\tool\ffmpeg-8.1.1-full_build\bin\ffmpeg.EXE
  OK  ffprobe  -> ...\ffprobe.EXE
  OK  yt-dlp   -> C:\Users\Admin\.local\bin\yt-dlp.EXE
  OK  data_root_writable -> D:\AI-workspace\Vidlearn AI\data
```

### 2.3 凭证安全（实测）
| 项 | 结果 |
|---|---|
| 后端 | `dpapi`（Windows 原生加密） |
| 密文含明文 | ❌ 否（实测 `secret123` 不在密文中） |
| 密文头 | `01000000d08c9ddf...`（标准 DPAPI 标识） |
| URL 编码处理 | ✅ `SESSDATA=test%2Csecret123` → `test,secret123` |
| 文件 ACL | 仅当前用户 `ADMIN\Admin:(F)` |

---

## 三、S1 期间发现并修复的问题

### 问题 1：ACL 导致凭证文件不可读（已修复）
- 现象：`icacls ... /grant:r {USERNAME}:F` 用了 `$env:USERNAME=Admin`，而真实账户是 `admin\admin`，导致 ACL 指向不存在的 `ADMIN\`，文件不可读。
- 修复：改用 `whoami` 获取真实限定名；`icacls` 失败时 **fail-open**（恢复继承），保证凭证始终可读。

### 问题 2：非 Windows 平台不能退化为明文落盘（已设计）
- 若 DPAPI 不可用：凭证仅存内存，`status()` 返回内存态，**绝不写明文**；`backend` 报告 `memory-only`。

---

## 四、接口对齐情况

| INTERFACE_CONTRACTS | 实现 |
|---|---|
| `CredentialProvider.get/set/clear/health` | ✅（`health` 以 `status` 实现） |
| Cookie 先 URL 解码 | ✅ |
| 日志脱敏 | ✅ |
| 任务状态机 CREATED→…→COMPLETED/FAILED + CANCELLED | ✅ |
| 媒体目录结构 | ✅ |

---

## 五、S1 Gate 判定

| Gate 条件 | 结果 |
|---|---|
| Python 3.12 / uv / FFmpeg 可运行 | ✅ |
| 配置可读取可校验 | ✅ |
| Cookie 可加密保存/解密使用 | ✅（DPAPI，密文不含明文） |
| Cookie 不入日志 | ✅ |
| 任务状态可创建/流转/异常 | ✅ |
| 媒体目录统一 | ✅ |

**S1 通过，可进入 S2（视频来源适配器）。**

---

## 六、遗留与移交 S2 的事项

1. **TaskManager 目前为内存实现**，S2 需替换为 SQLite 持久化（接口不变）。
2. **CredentialProvider 的 `status()` 目前只判断存在性**，未做真实有效性探测（调 `/x/web-interface/nav`）；建议 S2-04 接入 B站时补上 `health` 真实校验。
3. 依赖 `fastapi/uvicorn` 已加入运行环境；正式部署用 `uv sync` 安装 `pyproject.toml` 依赖。

---

## 七、运行方式

```powershell
# 安装依赖
uv pip install --python .venv\Scripts\python.exe -r pyproject.toml   # 或 uv sync
# 启动
.venv\Scripts\python.exe -m uvicorn apps.main:app --port 8123
# 健康检查
curl http://127.0.0.1:8123/api/health
# 测试
.venv\Scripts\python.exe -m pytest tests -q
```
