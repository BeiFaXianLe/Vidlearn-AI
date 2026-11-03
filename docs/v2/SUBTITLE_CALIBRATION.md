# 字幕校准（SUBTITLE_CALIBRATION）

> VidLearn AI V2.1 · 分层字幕纠错：术语表 → 同音纠错 → AI 校订 → 时间轴对齐 → 人工复核

## 1. 解决什么问题

语音识别（ASR）字幕常见错误分四类，处理手段完全不同：

| 类型 | 例子 | 方案 |
|---|---|---|
| 专有名词同音字 | 镜舟科技 → **金州/荆州**科技 | 术语表 + 模糊拼音纠错（L1/L2） |
| 一般错别字/漏字 | 词不达意、识别错词 | LLM 约束式校订（L3） |
| 断句/标点/繁简 | 无标点、繁体混入 | 已有标点恢复 + OpenCC |
| 时间轴偏移 | 字幕整体偏早/偏晚 | 静音检测估计全局偏移（L5） |

**原则**：先规则、后 AI；只改错字/标点，不改意思、不增删内容；原始字幕永远保留，可回退。

---

## 2. 分层架构

```
原始字幕轨（asr / asr_punct / 平台字幕…）
   │
   ├─ L0 质量评分      subtitle_qc.score_cues()      定位低质量段（0-100 分）
   ├─ L1 术语注入      glossary → ASR initial_prompt  提升源头识别率
   ├─ L2 同音纠错      pinyin_util（模糊拼音）         金州/荆州 → 镜舟
   ├─ L3 AI 校订       calibrate.allowed_fix() 校验    只允许错字/标点级修改
   ├─ L5 时间轴对齐    align.align_cues()             仅在检测到整体偏移时平移
   └─ 生成派生轨 asr_corrected（优先级高于 asr_punct，低于人工字幕）
        └─ caption_changes 变更日志 + caption_qc 评分
             └─ 人工复核（接受 / 撤销）
```

### L0 质量评分
指标：时长/字数比（语速异常）、重叠、非单调、空字幕、重复、时长过短/过长、覆盖度、命中的已知错误写法。
输出 0–100 分 + 问题段落列表，用于定位和展示。

### L1 术语表（glossary）
- 作用域：`global`（全局）或 `video`（单视频，优先）
- 来源：手动添加 / **从视频标题·作者·AI 总结的 terms 自动抽取**
- 双通道使用：① ASR 前作为 `initial_prompt` 热词；② ASR 后做同音替换

### L2 模糊拼音纠错（`apps/core/pinyin_util.py`）
- 只对连续中文片段匹配，英文/数字不参与
- **模糊归一**常见 ASR 混淆：前后鼻音（in/ing、en/eng、an/ang）、平翘舌（z/zh、c/ch、s/sh）、n/l、f/h、ü/v
  → 所以 `金州(jin)` 也能命中 `镜舟(jing)`
- 约束：等长 + 归一化拼音序列完全一致 + 与目标词不同；单个字的错误写法被忽略（防误伤）
- 精确同音置信度 0.9，模糊近音 0.6（复核时优先看低置信）

### L3 LLM 约束校订（`apps/core/calibrate.py`）
- 分批（默认 30 行）+ 术语表约束，提示词明确：只改同音字/错别字/标点，不改意思、不动时间
- **逐条校验 `allowed_fix()`**：长度比 0.6–1.6、字符相似度 ≥0.55、数字与英文集合不变、不得大段删改
- 不通过则丢弃该条（计入 `dropped_llm`）；无 LLM Key 时自动跳过

### L5 时间轴对齐（`apps/core/align.py`）
- FFmpeg `silencedetect` 找静音，得到语音区间
- **只在检测到明显整体偏移（|中位偏移| ≥ 350ms）时整体平移**；已对齐的 ASR 字幕默认不动（偏移≈0 → 0 改动）
- **保险**：对齐后若质量分下降则放弃（保护已对齐轨道）

### 人工复核（UI）
- 「章节与字幕」Tab 顶部：质量徽章 + `校准字幕 / 术语表 / 查看改动 / 补标点`
- 复核弹窗：逐条 `原(红删除线) → 新(绿)`，标注原因与置信度，可筛选「仅低置信」
- 支持「撤销本次校准」= 删除派生轨，回退到原轨（原始轨从未被修改）

---

## 3. 数据模型（schema v7）

| 表 | 用途 |
|---|---|
| `glossary` | 术语（term / variants / scope / video_id / category / weight / enabled） |
| `caption_changes` | 变更日志（before / after / reason / confidence / time_from / time_to） |
| `caption_qc` | 每轨质量报告（score + report_json） |

派生轨：`source_captions.source_type = 'asr_corrected'`；优先级：
`bilibili_human(1) > bilibili_ai(2) > user(3) > embedded(4) > asr_corrected(5) > asr_punct(6) > asr(7)`

---

## 4. API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/glossary?video_id=` | 术语列表（含全局+该视频） |
| POST | `/api/glossary` | 新增 `{term, variants[], category, scope, video_id}` |
| PATCH/DELETE | `/api/glossary/{id}` | 修改/删除 |
| POST | `/api/glossary/extract` | 从标题/总结抽取候选 `{video_id, save}` |
| GET | `/api/videos/{id}/subtitle-qc` | 质量评分 + 问题段 |
| POST | `/api/videos/{id}/calibrate` | 异步校准任务 `{caption_id?, do_llm, do_align}` |
| GET | `/api/videos/{id}/caption-changes` | 变更日志 |
| POST | `/api/videos/{id}/preferred-caption` | 指定首选字幕轨 |
| DELETE | `/api/videos/{id}/captions/{cid}` | 删除某轨（撤销校准/回退） |

---

## 5. 实测

- 真实案例（截图）：`北京金州科技有限公司` / `荆州科技` → **`北京镜舟科技有限公司` / `镜舟科技`**
- 963 段真实 ASR 字幕：偏移估计 53ms（判定已对齐）→ 0 改动，质量 98 分保持不变
- 演示视频（3 段）：质量 73.2 → 79.2，2 处同音纠错，复核可逐条查看
- 回归：**189 个单元测试通过**（含 variants JSON 字符串、单字误伤、对齐不降分等回归用例）

---

## 6. 已知限制与后续

1. 模糊拼音可能误伤少量近音词 → 已用「等长+序列一致+单字忽略 + 低置信标注 + 可回退」兜底；建议把品牌/人名加入术语表
2. L3 依赖云端 LLM（仅发送字幕文本），无 Key 时自动跳过，不影响 L1/L2/L5
3. L5 为「全局偏移」级对齐；若需**逐词强对齐**（任意文本+音频），可另接 `stable-ts`/`whisperx`（需 torch，默认不装）
4. 术语自动抽取是启发式，需人工确认后入库
