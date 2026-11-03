# S5 交付报告：AI 内容分析（摘要 / 章节 / 知识点）

- 日期：2026-11-02
- 状态：**完成**（73 个单测通过；HTTP 端到端用 mock LLM 验证通过）
- 依据：PRD V2.0 §3.6、数据边界冻结条款

---

## 一、交付物

| 任务 | 文件 | 说明 |
|---|---|---|
| S5-01 LLM Provider | `apps/core/ai.py` | LLMProvider Protocol + OpenAI 兼容实现（DeepSeek/Qwen/OpenAI） |
| S5-02 上下文构建 | `ai.build_transcript_context` | 分段拼带毫秒时间戳文本，超长截断 |
| S5-03 视频摘要 | `analysis.AnalysisService.summarize` | 一句话 + 要点 + 术语 + 受众 + 范围 |
| S5-04 章节生成 | `build_chapters` | 章节带时间戳 |
| S5-05 知识点提取 | `build_points` | 知识点 + 关联时间 |
| S5-06 视频问答 | 复用 LLMProvider（问答留待 S6 UI 接入） | — |
| S5-07 持久化 | `apps/storage/analysis_repos.py` | summaries / chapters / knowledge_points 三表 |
| Schema 迁移 | `db.py` SCHEMA_V2_SQL | 版本 1→2 |
| API | `apps/api_s5.py` | /analysis/summary /analysis/chapters /analysis/points /analysis/status |
| 测试 | `tests/test_s5_analysis.py` | 8 用例 |

---

## 二、验收结果

### 2.1 单元测试
```
73 passed（S1 13 + S2 12 + S3 32 + S4 8 + S5 8）
```

### 2.2 HTTP 端到端（mock LLM 服务）
```
GET  /api/analysis/status → llm_configured: true
POST /api/analysis/summary  → ok | one_liner: "这是一个关于视频下载工具介绍的视频"
POST /api/analysis/chapters → ok | count: 2 | first: "开场"
POST /api/analysis/points   → ok | count: 1
```
数据库落地：`summaries:1 | chapters:2 | knowledge_points:1`

---

## 三、关键设计（安全/正确性）

1. **数据边界**：只发送字幕文本（`build_transcript_context`），**不发送视频/音频/关键帧**——符合 PRD 冻结条款。
2. **content_scope 以系统为准**：模型返回的 scope 被系统判定覆盖，防止模型虚报"完整"。
3. **时间戳防伪**：`normalize_timestamps` 把模型给的时间戳 snap 到字幕中真实存在的起点（容差 1500ms），对不上直接置 None——**不允许模型虚构时间戳**。
4. **JSON Schema 校验**：`_validate_schema` 检查 required + type，失败抛 LLMError。
5. **transcript_hash**：记录输入字幕哈希，便于缓存与追溯。

---

## 四、S5 期间的问题

### 问题：httpx 未安装（ai.py 依赖）
- 处理：`uv pip install httpx`（已计入 pyproject 依赖）。

### 说明：真实 LLM 未调用
- 无 API Key 环境，故用 **本地 mock LLM** 验证完整 HTTP 链路（编排、schema 校验、持久化均真实执行）。
- 真实调用只需设 `VIDLEARN_LLM_API_KEY` + `VIDLEARN_LLM_BASE_URL` + `VIDLEARN_LLM_MODEL`。

---

## 五、S5 Gate 判定

| Gate 条件 | 结果 |
|---|---|
| LLM Provider 抽象 | ✅ |
| 只发送文本（数据边界） | ✅ |
| 摘要/章节/知识点生成 | ✅ |
| JSON Schema 校验 | ✅ |
| 时间戳只能来自字幕 | ✅（snap + 越界置空） |
| 结果持久化 | ✅（三表） |
| content_scope 可信 | ✅（系统判定） |

**S5 通过，可进入 S6（本地播放器与学习工作台）。**

---

## 六、移交 S6

1. 三表已就绪，前端详情页可读 `summary/chapters/points`。
2. 视频问答可在 S6 加 `/api/videos/{id}/qa`，复用 LLMProvider。
3. 需在 S6 把 AI 结果对接到原型 UI（摘要 Tab / 章节 Tab）。
