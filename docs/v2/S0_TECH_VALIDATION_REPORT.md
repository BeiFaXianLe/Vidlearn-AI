# S0 技术验证总报告

> VidLearn AI V2.0 · S0 阶段交付
> 日期：2026-11-02
> 结论：**S0 通过（抖音除外，已决策暂缓）**

---

## 一、执行摘要

| PoC | 内容 | 结论 |
|---|---|---|
| S0-01 | B站登录态（Cookie） | ✅ **通过** |
| S0-02 | B站平台字幕 | ⚠️ **部分通过**（可取但有错位不稳定） |
| S0-03 | 抖音下载 | ⏸ **暂缓**（当前开源方案被风控阻断） |
| S0-04 | 长音频 ASR | ✅ **通过**（有 1 处需修复） |
| S0-05 | 媒体完整性 | ✅ **通过** |

**可以进入 S1 正式开发。** 抖音不影响 S1–S7 主链路。

---

## 二、各 PoC 结论与关键约束

### S0-01 B站登录（通过）
- 有效 SESSDATA（**解码后**）→ `isLogin=true`，可正常下载/取字幕。
- ⚠️ **D02 实现要求**：粘贴的 Cookie 必须先 **URL 解码**（用户首次给的编码形式导致 `-101 未登录`）。
- 安全：SESSDATA 仅临时使用，验证后销毁；正式实现走 DPAPI 加密。

### S0-02 B站平台字幕（部分通过）
- 登录态可取得 `ai-zh` AI 字幕，可区分 `ai_type`（人工/ AI）。
- ❌ **严重问题**：同一 `aid+cid` 连续请求返回不一致（55 / 138 / 173 条；出现末条 306s、309s 远超视频 106s 的错位内容）。
- ⚠️ **强制实现约束**：
  1. 字幕末条时间 ≤ 视频时长 + 2s，否则丢弃重取；
  2. 重取 N 次（建议 3），取"时间戳合理"的那份；
  3. `subtitle_url` 的 `auth_key` 有时效，每次重新请求 `/x/player/v2`；
  4. cid 权威来自 `/x/web-interface/view` 的 `data.cid`。

### S0-03 抖音（暂缓）
- `jiji262/douyin-downloader` CLI 实测 403 `Blocked by ArgusSecurityPlugin`，加 Cookie 无效。
- 页面上下文（Playwright）实测返回 200 → 技术上可行，但需登录态 + 长期维护。
- **决策：本轮不接入，保留 `DouyinAdapter` 接口 + 降级提示，后续评估。**

### S0-04 长音频 ASR（通过）
- 74s → 3 段切片 + 合并，时间戳 0 越界 0 重叠，RTF 0.194。
- ⚠️ **缺陷**：硬切导致句子截断/重复（"工作站"→"工作"+"作战"）。**S4 必须重叠切片 + 边界去重**。
- ⚠️ **首次模型加载 600s**（460MB 下载）→ 必须预置模型 + 加载超时提示。

### S0-05 媒体完整性（通过）
- 5 类样本判定正确（verified / invalid / likely）。
- ⚠️ MKV 流级 duration 常缺失，退化用容器时长；无音轨对 ASR 场景判 `likely`；部分截断需尾部解码补判。

---

## 三、已验证可用的技术链路

```
B站 URL ──yt-dlp(匿名/登录态)──► 视频(最高1080P,视视频权限) + 音频
                                      │
                                      ├─ FFprobe 完整性校验(5指标) ──► media_assets
                                      │
             登录态字幕 API ──► 平台 AI 字幕(强校验+重取) ──► source_captions
                                      │  （无/不合格时）
                                      ▼
                     FFmpeg 提取 16k PCM ──► faster-whisper(切片+重叠+合并) ──► transcript_segments
                                      │
                                      ▼
                         云端 LLM（仅文本）──► 摘要/章节/知识点
                                      │
                                      ▼
                          本地 HTTP Range 播放 + 字幕同步 + 章节跳转
```

已实测通过：yt-dlp 下载（含 1080P）、FFprobe/FFmpeg、faster-whisper 转写、完整性判定、登录态字幕。

---

## 四、S0 未覆盖/待补（不阻塞 S1）

1. 人工字幕样本（本批只有 AI 字幕）。
2. 抖音页面上下文方案的完整链路验证（已决策暂缓）。
3. ≥30 分钟真实长视频端到端（本次用 74s 合成音频验证切片逻辑）。
4. 云端 LLM 实际调用与结构化输出（S5 阶段验证）。

---

## 五、证据索引

| 文档 | 内容 |
|---|---|
| [S0_能力实测报告.md](evidence/S0_能力实测报告.md) | B站/抖音/FFmpeg/faster-whisper 基础能力实测 |
| [S0-01_02_B站登录与字幕PoC结果.md](evidence/S0-01_02_B站登录与字幕PoC结果.md) | 登录 + 平台字幕（含不稳定证据） |
| [S0-03_抖音PoC结果.md](evidence/S0-03_抖音PoC结果.md) | 抖音 403 证据 + 页面上下文实测 + 替代路线 |
| [S0-04_05_ASR与完整性PoC结果.md](evidence/S0-04_05_ASR与完整性PoC结果.md) | 长音频切片合并 + 完整性判定 |
| [S0-B_登录态与抖音方案.md](evidence/S0-B_登录态与抖音方案.md) | 登录态可行性与抖音方案对比 |

配套：[DEPENDENCY_VERSIONS.md](DEPENDENCY_VERSIONS.md) · [INTERFACE_CONTRACTS.md](INTERFACE_CONTRACTS.md) · [KNOWN_RISKS.md](KNOWN_RISKS.md)

