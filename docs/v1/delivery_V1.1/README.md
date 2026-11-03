# VidLearn AI V1.1 调整版交付包

本次仅调整处理流程与后台技术方案，已确认的高保真 HTML 页面原型保持原样。

文件：
- `VidLearn_AI_Prototype.html`：原型原样保留。
- `VidLearn_AI_PRD_V1.1.md`：调整后的详细 PRD。
- `VidLearn_AI_Development_Plan_V1.1.md`：调整后的开发阶段和任务。
- `DeepSeek_Harness_Audit_Prompt_V1.1.md`：更新后的代码审查与媒体工具验证提示词。
- `VidLearn_AI_Change_Log.md`：本次变更与不变项。

建议先看 Change Log，再阅读 PRD，随后用 Harness 提示词审查 yt-dlp、FFmpeg、BiliSum 和 Muku。不要在 S0 验证完成前宣称任意站点均可下载。

## 本次核心架构
网络 URL / 本地文件 → 本地媒体资产 → FFprobe/FFmpeg → 原始字幕优先 → 云端 ASR 兜底 → 完整性检查 → AI 总结/章节/知识点。

## 使用说明
HTML 原型仍是静态交互演示，不接真实下载器、ASR 或后端。原型的视觉结构不变，正式产品需要在现有导入入口中加入本地文件上传，并把播放器数据源调整为本地媒体优先。
