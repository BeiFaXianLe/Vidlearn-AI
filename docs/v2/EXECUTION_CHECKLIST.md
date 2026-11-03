# VidLearn AI 执行清单（V2.0 基线）

> 基线：PRD V2.0 + Development Plan V2.0（决策已冻结）
> 更新：2026-11-02 ｜ 工程估算 41–56 人日，预算上限 66 人日
> 状态：`[ ]` 待办 · `[~]` 进行中 · `[x]` 完成 · `[!]` 阻塞

## 冻结基线速查

| 项 | 值 |
|---|---|
| 平台 | Windows First |
| Cookie 加密 | Windows DPAPI（D01） |
| B站登录 | 手动粘贴 Cookie（D02） |
| 抖音 | jiji262/douyin-downloader 独立子进程（D03/D04/D05） |
| ASR | 本地 faster-whisper，FFmpeg 16k PCM，不用 PyAV |
| 字幕优先级 | 平台 → 内嵌 → 本地 ASR |
| 云端 AI | 仅文本，不上传音视频/关键帧 |
| 视频保留 | 永久，用户手动删除 |

---

## S0 技术验证（✅ 已完成）

- [x] 环境体检（Python 3.12 / yt-dlp 2026.10.26 / FFmpeg 8.1.1 / Node 24 / 453GB）
- [x] B站匿名能力实测：720P 可下、平台字幕为空
- [x] faster-whisper 基准：RTF 0.13 / 相似度 0.954
- [x] 内嵌字幕提取、截断检测、720P 下载+FFprobe 校验
- [x] S0-01 B站登录 PoC **通过**：SESSDATA（解码后）→ isLogin=true、VIP=1；注意必须 URL 解码 → 见 [evidence/S0-01_02_B站登录与字幕PoC结果.md](evidence/S0-01_02_B站登录与字幕PoC结果.md)
- [~] S0-02 B站平台字幕 PoC **部分通过**：登录可取得 ai-zh 字幕；但发现**同一 cid 返回不稳定**（55/138/173 条，含超时长错位）→ 必须强校验时间戳 + 重取
- [!] S0-03 抖音下载 PoC **当前方案未通过**：CLI 实测 403 `ArgusSecurityPlugin`，加 Cookie 无效；但页面上下文实测返回 200（可行，需登录态+浏览器）→ 见 [evidence/S0-03_抖音PoC结果.md](evidence/S0-03_抖音PoC结果.md) 待定路线
- [x] S0-04 长音频 ASR PoC **通过**：3 段切片+合并，时间戳 0 问题，RTF 0.194；缺陷=硬切截断句子（需重叠+边界去重）→ [evidence/S0-04_05_ASR与完整性PoC结果.md](evidence/S0-04_05_ASR与完整性PoC结果.md)
- [x] S0-05 完整性 PoC **通过**：5 类样本判定正确（verified/invalid/likely）；MKV 需退化容器时长、无音轨判 likely
- [x] S0 正式交付物已完成：S0_TECH_VALIDATION_REPORT / DEPENDENCY_VERSIONS / INTERFACE_CONTRACTS / KNOWN_RISKS

> 验收标准见 [PoC_Acceptance_Criteria_V2.0.md](PoC_Acceptance_Criteria_V2.0.md)

## S1 基础设施和凭证管理（✅ 已完成，见 S1_DELIVERY_REPORT.md）

- [x] S1-01 Windows 开发环境（Python 3.12 / uv / FFmpeg）
- [x] S1-02 配置管理（可读取、可校验）
- [x] S1-03 CredentialProvider 统一接口
- [x] S1-04 DPAPI 加密保存与解密使用
- [x] S1-05 Cookie 手动粘贴导入 + 格式转换
- [x] S1-06 日志脱敏（Cookie 不入日志/异常堆栈）
- [x] S1-07 TaskManager（创建、状态、异常）
- [x] S1-08 媒体目录统一存储路径

## S2 视频来源适配器（✅ 已完成，见 S2_DELIVERY_REPORT.md）

- [x] S2-01 VideoAdapter 统一接口
- [x] S2-02 LocalFileAdapter
- [x] S2-03 B站匿名模式
- [x] S2-04 B站登录模式
- [x] S2-05 B站平台字幕获取
- [~] S2-06 DouyinAdapter（暂缓，保留接口+unsupported）
- [~] S2-07 抖音子进程（暂缓）
- [x] S2-08 下载进度/失败/重试
- [x] S2-09 错误分类（登录失效/网络/权限/格式变更）

## S3 媒体资产和字幕处理（✅ 已完成，见 S3_DELIVERY_REPORT.md）

- [x] S3-01 MediaAsset 模型
- [x] S3-02 FFprobe 信息提取
- [x] S3-03 完整性多指标校验
- [x] S3-04 内嵌字幕提取（SubRip 等）
- [x] S3-05 用户字幕导入
- [x] S3-06 平台字幕标准化（秒→毫秒）
- [x] S3-07 Transcript 标准化分段模型
- [x] S3-08 字幕覆盖率/完整性
- [x] S3-09 状态管理流转

## S4 本地 ASR（✅ 已完成，见 S4_DELIVERY_REPORT.md）

- [x] S4-01 FFmpeg 提取 16kHz 单声道 PCM
- [x] S4-02 ASRProvider 统一接口
- [x] S4-03 faster-whisper CPU int8
- [x] S4-04 长音频切片
- [x] S4-05 结果合并（时间戳连续）
- [x] S4-06 识别完整性/失败状态
- [x] S4-07 云端 ASR 接口预留

## S5 AI 内容分析（✅ 已完成，见 S5_DELIVERY_REPORT.md）

- [x] S5-01 LLM Provider
- [x] S5-02 Transcript Context Builder
- [x] S5-03 视频摘要
- [x] S5-04 章节生成（带时间戳）
- [x] S5-05 知识点提取
- [x] S5-06 视频问答
- [x] S5-07 分析结果持久化
- [x] 数据安全门禁：云端仅文本

## S6 本地播放器与学习工作台（✅ 已完成，见 S6_DELIVERY_REPORT.md）

- [x] S6-01 后端安全媒体访问
- [x] S6-02 HTTP Range
- [x] S6-03 本地播放器
- [x] S6-04 编码兼容（H.264 优先）
- [x] S6-05 字幕同步
- [x] S6-06 章节跳转
- [x] S6-07 接入现有原型

## S7 视频库和业务闭环（✅ 已完成，见 S7_DELIVERY_REPORT.md）

- [x] S7-01 导入 UI（链接 + 文件）
- [x] S7-02 视频 Gallery
- [x] S7-03 视频详情
- [x] S7-04 学习进度保存/恢复
- [x] S7-05 笔记持久化
- [x] S7-06 删除（资料/文件/全部）
- [x] S7-07 端到端测试

## S8 安全、稳定性与发布（✅ 已完成，见 S8_DELIVERY_REPORT.md）

- [x] S8-01 凭证安全（DPAPI + 日志脱敏）
- [~] S8-02 子进程隔离（抖音暂缓；其余已隔离）
- [x] S8-03 路径安全
- [x] S8-04 任务恢复
- [x] S8-05 长视频压力测试
- [x] S8-06 许可证检查
- [x] S8-07 Windows 打包






