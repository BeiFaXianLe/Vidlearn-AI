# V2.0 文档（当前基线）

> V2.0 决策已冻结并已实现（S0–S8 全部完成，91 个单测通过）。

## 需求与计划
| 文档 | 说明 |
|---|---|
| [PRD_V2.0.md](PRD_V2.0.md) | 产品需求文档（含 D01–D05 冻结决策） |
| [Development_Plan_V2.0.md](Development_Plan_V2.0.md) | 开发计划（S0–S8，41–56 人日） |
| [Architecture_Decisions_V2.0.md](Architecture_Decisions_V2.0.md) | 架构决策记录 |
| [PoC_Acceptance_Criteria_V2.0.md](PoC_Acceptance_Criteria_V2.0.md) | S0 PoC 验收标准与门禁 |
| [EXECUTION_CHECKLIST.md](EXECUTION_CHECKLIST.md) | 可勾选执行清单（已全部完成） |

## 技术规范
| 文档 | 说明 |
|---|---|
| [DEPENDENCY_VERSIONS.md](DEPENDENCY_VERSIONS.md) | 依赖版本锁定 |
| [INTERFACE_CONTRACTS.md](INTERFACE_CONTRACTS.md) | Adapter/Provider 接口契约 |
| [KNOWN_RISKS.md](KNOWN_RISKS.md) | 已知风险清单 |
| [LICENSE_AUDIT.md](LICENSE_AUDIT.md) | 许可证审查（FFmpeg GPL 注意） |
| [MODEL_SETUP.md](MODEL_SETUP.md) | ASR 模型下载与配置 |
| [SUBTITLE_PIPELINE.md](SUBTITLE_PIPELINE.md) | 字幕三级回退（平台→内嵌→ASR） |
| [PUNCTUATION.md](PUNCTUATION.md) | 字幕标点恢复（LLM 派生轨） |
| [UI_NOTES.md](UI_NOTES.md) | 前端 UI 结构与交互（对齐原型 V1.1） |
| [V2_FEATURES.md](V2_FEATURES.md) | 磁盘/批量导入/收藏/任务控制/问答 |
| [DEPLOY_LINUX.md](DEPLOY_LINUX.md) | **Linux 部署方案**（systemd / Docker / Nginx / 迁移） |
| [DEPLOY_MACOS.md](DEPLOY_MACOS.md) | **macOS 部署方案**（launchd / Homebrew / Docker） |

## 阶段交付报告
| 阶段 | 报告 |
|---|---|
| S0 | [S0_TECH_VALIDATION_REPORT.md](S0_TECH_VALIDATION_REPORT.md) |
| S1 | [S1_DELIVERY_REPORT.md](S1_DELIVERY_REPORT.md) |
| S2 | [S2_DELIVERY_REPORT.md](S2_DELIVERY_REPORT.md) |
| S3 | [S3_DELIVERY_REPORT.md](S3_DELIVERY_REPORT.md) |
| S4 | [S4_DELIVERY_REPORT.md](S4_DELIVERY_REPORT.md) |
| S5 | [S5_DELIVERY_REPORT.md](S5_DELIVERY_REPORT.md) |
| S6 | [S6_DELIVERY_REPORT.md](S6_DELIVERY_REPORT.md) |
| S7 | [S7_DELIVERY_REPORT.md](S7_DELIVERY_REPORT.md) |
| S8 | [S8_DELIVERY_REPORT.md](S8_DELIVERY_REPORT.md) |

## 证据（evidence/）
| 文档 | 说明 |
|---|---|
| [evidence/S0_能力实测报告.md](evidence/S0_能力实测报告.md) | B站/抖音/FFmpeg/faster-whisper 实测 |
| [evidence/S0-01_02_B站登录与字幕PoC结果.md](evidence/S0-01_02_B站登录与字幕PoC结果.md) | 登录 + 平台字幕（含错位证据） |
| [evidence/S0-03_抖音PoC结果.md](evidence/S0-03_抖音PoC结果.md) | 抖音 403 证据 + 替代路线 |
| [evidence/S0-04_05_ASR与完整性PoC结果.md](evidence/S0-04_05_ASR与完整性PoC结果.md) | 长音频切片 + 完整性判定 |
| [evidence/S0-B_登录态与抖音方案.md](evidence/S0-B_登录态与抖音方案.md) | 登录态可行性与抖音方案对比 |
| [evidence/V2.0_原始导出正文.md](evidence/V2.0_原始导出正文.md) | V2.0 冻结方案原文归档 |


