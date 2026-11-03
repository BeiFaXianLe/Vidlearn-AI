# 接口契约（INTERFACE_CONTRACTS）

> VidLearn AI V2.0 · S0 约定
> 目的：先定接口，供 S1–S7 并行开发。标注 **[S0 证据]** 的字段/行为来自实测。

---

## 1. VideoAdapter（视频来源统一接口）

```python
class VideoAdapter(Protocol):
    name: str                     # "bilibili" | "douyin" | "local"
    async def can_handle(self, url: str) -> bool: ...
    async def probe(self, url: str) -> VideoMeta: ...      # 只取元数据，不下载
    async def fetch_media(self, url: str, opts: FetchOpts) -> MediaResult: ...

@dataclass
class VideoMeta:
    platform: str
    platform_video_id: str        # BV号 / aweme_id / 本地 hash
    title: str
    author: str | None
    duration_ms: int
    cover_url: str | None
    available_heights: list[int]  # [S0 证据] yt-dlp formats 的 height 去重
    has_subtitle_tracks: bool

@dataclass
class MediaResult:
    file_path: str                # 临时区路径（未校验前）
    container: str
    sha256: str
    declared_duration_ms: int
    error_code: str | None        # 见 §6 错误码
```

**约束**
- 子进程调用一律参数数组，不拼 shell。
- 下载落 `media/temp/`，校验通过后原子移入 `media/original/`。

---

## 2. CredentialProvider（凭证）

```python
class CredentialProvider(Protocol):
    def get(self, platform: str) -> dict[str, str] | None: ...   # 明文仅内存
    def set(self, platform: str, raw: str) -> None: ...          # 加密落盘
    def clear(self, platform: str) -> None: ...
    def health(self, platform: str) -> CredStatus: ...           # valid/expired/missing
```

**约束**
- **[S0 证据] 输入必须先 URL 解码**：`urllib.parse.unquote(raw_sessdata)`；编码形式会被 B站判 `-101`。
- 存储：Windows DPAPI 加密；明文仅驻留内存，用完即弃。
- 日志：任何日志/异常栈不得包含 cookie 值（脱敏器统一处理 `SESSDATA=`、`ttwid=` 等）。

---

## 3. SubtitleProvider（字幕）

```python
class SubtitleProvider(Protocol):
    async def list_tracks(self, media: MediaRef) -> list[SubtitleTrack]: ...
    async def fetch_track(self, track: SubtitleTrack) -> list[RawCue]: ...

@dataclass
class SubtitleTrack:
    source: str          # "bilibili_ai" | "bilibili_human" | "embedded" | "user" | "asr"
    language: str        # "zh-CN" | "en-US" ...
    is_ai_generated: bool
    url: str | None      # 平台字幕下载地址（含 auth_key，短时效）

@dataclass
class RawCue:
    start_ms: int
    end_ms: int
    text: str
```

**约束 [S0 证据]**
1. 平台字幕 `body[].from/to` 单位为**秒**（浮点）→ ×1000 取整为毫秒。
2. **每轮重新请求 `/x/player/v2` 获取新 `auth_key`**，复用旧 URL 会返回空。
3. **强校验**：`max(end_ms) <= media_duration_ms + 2000`，否则视为污染，重取（≤3 次）。
4. 全部失败 → 该轨道 `invalid`，降级到 embedded → ASR。

---

## 4. ASRProvider（本地语音识别）

```python
class ASRProvider(Protocol):
    async def transcribe(self, media: MediaRef, opts: AsrOpts) -> TranscriptResult: ...

@dataclass
class AsrOpts:
    language: str = "zh"
    model: str = "small"          # small/medium/large-v3
    device: str = "cpu"
    compute_type: str = "int8"
    segment_sec: int = 30
    overlap_sec: int = 2          # [S0 证据] 必须 >0，防硬切截断

@dataclass
class TranscriptResult:
    units: list[RawCue]
    model: str
    language: str
    rtf: float
    status: str                   # complete/partial/failed
```

**约束 [S0 证据]**
1. 音频统一由 FFmpeg 解为 **16kHz 单声道 PCM**，不依赖 PyAV。
2. 切片必须**重叠 1–2 秒**，合并时按文本相似度**去重**边界。
3. 合并后校验：时间戳单调、不重叠、不越界（`end_ms <= duration_ms + 容差`）。
4. 模型**预置**，首次加载不得阻塞用户（>30s 应有进度提示）。

---

## 5. MediaIntegrity（完整性与处理状态机）

```python
@dataclass
class IntegrityReport:
    verdict: str      # verified | likely | partial | unknown | invalid
    checks: dict      # 每项指标的结果
    reasons: list[str]
```

**判定指标（多指标，禁止单一）[S0 证据]**
1. 容器可解析（moov / 结构）
2. 容器时长 vs 流时长 vs 元数据时长（差值 >2% 或 >1s 记异常）
3. 完整解码 `ffmpeg -f null -` 退出码
4. 尾部 2s 解码
5. 音视频流存在性（**用途感知**：无音轨 → ASR 场景判 `likely` 而非 `verified`）

**任务状态机 [PRD 冻结]**
```
CREATED → MEDIA_PROCESSING → MEDIA_READY
→ TRANSCRIPT_PROCESSING → TRANSCRIPT_READY
→ AI_ANALYZING → COMPLETED / FAILED
```

---

## 6. 统一错误码

| code | 含义 | 触发场景 |
|---|---|---|
| `need_login` | 需登录/Cookie 失效 | B站返回 `-101`；子进程鉴权失败 |
| `format_changed` | 平台结构变化 | yt-dlp 解析失败、extractor 失效 |
| `blocked` | 平台风控拦截 | 抖音 `ArgusSecurityPlugin` 403 |
| `not_authorized` | 无权获取 | 会员/付费/地区限制 |
| `network` | 网络错误 | 超时、DNS、断连 |
| `media_invalid` | 媒体不可用 | 完整性判定 invalid |
| `media_no_audio` | 无音轨 | ASR 不可用 |
| `subtitle_unreliable` | 字幕校验失败 | 时间戳越界/污染 |
| `quota` | 磁盘/配额不足 | 存储限制 |

---

## 7. AIProvider（云端 LLM）

```python
class LLMProvider(Protocol):
    async def complete_json(self, prompt: str, schema: dict) -> dict: ...
```

**约束 [PRD 冻结]**
- **只发送文本**（字幕/转写/提示词），禁止上传视频、音频、关键帧。
- 输出必须 JSON Schema 校验，失败重试并记录。
- 时间戳只能来自字幕/ASR/人工，**不得由模型生成**。

---

## 8. 媒体播放接口

- `GET /api/videos/{id}/media` → 受控 **HTTP Range**，支持拖动。
- 鉴权后返回，**不得把 `media/` 目录暴露为静态目录**。
- 优先 **H.264(avc1)** 流；非 H.264 原生播放优先，必要时转码。
