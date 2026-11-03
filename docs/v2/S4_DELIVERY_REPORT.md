# S4 交付报告：本地 ASR

- 日期：2026-11-02
- 状态：**完成**（65 个单测通过，含真实转写；HTTP 端到端通过）
- 依据：PRD V2.0 §3.5、S0-04 实测约束

---

## 一、交付物

| 任务 | 文件 | 说明 |
|---|---|---|
| S4-01 音频提取 | `apps/core/asr.py:extract_audio_16k` | FFmpeg → 16kHz 单声道 PCM（不用 PyAV） |
| S4-02 ASRProvider | `apps/core/asr.py` | Provider 抽象 + FasterWhisperASR 实现 |
| S4-03 faster-whisper | 同上 | CPU int8，模型懒加载缓存 |
| S4-04 长音频切片 | `split_with_overlap` | 重叠切片（默认 2s） |
| S4-05 结果合并 | `_dedupe_boundary` | 边界重复去重 + 排序 |
| S4-06 完整性 | `_validate` | 单调/不重叠/不越界校验 |
| S4-07 云端预留 | — | 接口抽象已留（ASRProvider Protocol） |
| API | `apps/api_s4.py` | POST /api/asr、GET /api/asr/status |
| 入库 | `CaptionIntake.add_track(source_type="asr")` | 转写结果落 source_captions + transcript_segments |
| 测试 | `tests/test_s4_asr.py` | 8 用例（切片/去重/校验/音频提取/真实转写） |

---

## 二、验收结果

### 2.1 单元测试
```
65 passed（S1 13 + S2 12 + S3 32 + S4 8）
```
S4 8 项含真实转写（4.25s 内完成，模型走本地缓存）。

### 2.2 HTTP 端到端
```
POST /api/intake {source: tts_video.mp4, purpose:"asr", also_subtitles:false}
→ ok: True, captions: None（无字幕，正确触发 ASR）
POST /api/asr {video_id: ...}
→ ok: True | status: complete | cues: 1 | rtf: 0.376
→ 文本: "大家好,今天我们来讲一下视频学习工作战则。"
GET /api/videos/{id}/transcript
→ segments in db: 1（已入库）
```

---

## 三、关键实现要点（全部来自 S0 实测）

1. **不用 PyAV**：音频统一 `ffmpeg -vn -ar 16000 -ac 1 -c:a pcm_s16le`，规避 faster-whisper 1.2.1 与 PyAV 19 的 `metadata_errors` 不兼容。
2. **重叠切片**：`segment_sec=30, overlap_sec=2`，防 S0 发现的"工作站→工作+作战"截断。
3. **边界去重**：`_dedupe_boundary` 比对前段尾/后段首文本，重叠部分裁掉。
4. **时间戳校验**：合并后检查单调、不重叠、不越界（>时长+2s）。
5. **RTF 实测 0.376**（比 S0 的 0.19 略高，因该样本 5s 太短，固定开销占比大）。

---

## 四、S4 期间的环境问题与处理

### 问题：模型首次下载卡住（HF 直连不稳定）
- 现象：`huggingface_hub` 直连下载 2.5MB 后停滞，测试挂起 >10 分钟。
- 处理：改用 **HF 镜像 `https://hf-mirror.com`** 完成下载（460MB，约 9 分钟），之后设 `HF_HUB_OFFLINE=1` 走本地缓存。
- **产品化建议**：把"预置模型"纳入安装流程（`DEPENDENCY_VERSIONS.md` 已记），并提供加载进度提示。这也印证了 S0 报告中"模型必须预置"的结论。

---

## 五、S4 Gate 判定

| Gate 条件 | 结果 |
|---|---|
| FFmpeg 提取 16k PCM | ✅ |
| ASRProvider 抽象 | ✅ |
| faster-whisper 本地 CPU int8 | ✅ |
| 长音频重叠切片 + 合并去重 | ✅ |
| 时间戳校验 | ✅ |
| 结果入库为 asr 轨 | ✅ |
| 无音轨/失败可识别 | ✅（extract_audio 抛 MEDIA_NO_AUDIO） |

**S4 通过，可进入 S5（AI 内容分析）。**

---

## 六、移交 S5

1. `apps/core/ai.py` 已建：LLMProvider + OpenAI 兼容实现 + JSON Schema 校验 + 时间戳防伪（snap）。
2. S5 需接 API：摘要/章节/知识点生成 + 持久化（summaries/chapters/knowledge_points 表）。
3. **数据边界**：只发文本，不发音视频。
4. 需用户提供 LLM API Key（或用本地 Ollama）。
