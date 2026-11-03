# 抖音（Douyin）支持说明

> VidLearn AI V2.2 · 基于 yt-dlp 内置 Douyin 解析器

## 方案
不自行实现抖音解析/签名，直接复用 **yt-dlp 内置的 `Douyin` extractor**（与 B 站共用好莱坞式下载管线）：
- `apps/adapters/douyin.py` —— `DouyinAdapter`（probe / fetch_media）
- 路由：`resolve_adapter()` 识别 `douyin.com` / `v.douyin.com` / 含链接的分享文案
- 能力复用：下载、完整性校验、MKV/MOV→MP4、本地 ASR、AI 分析、字幕校准、任务管理

## 用法
导入页粘贴即可，**每行一个**：
```
https://v.douyin.com/iRxAbcDe/
https://www.douyin.com/video/7345678901234567890
7.99 复制打开抖音... https://v.douyin.com/iRxAbcDe/ 好看   ← 整段分享文案也能自动提取链接
```

## Cookie（可选）
部分视频/高清需要登录态。导入页粘贴抖音 Cookie（通常含 `ttwid`、`sessionid`、`msToken` 等），系统会按来源**自动存到 douyin 平台**（加密保存，仅当前用户可读，绝不上传）。

## 字幕
抖音一般无平台字幕 → 自动走**本地 ASR**（faster-whisper），再经「字幕校准」纠正同音错字。

## 已知限制 / 风险
- 抖音反爬较强，**可能间歇性返回 403/验证码**（错误码 `blocked`，可重试）；换网络或补 Cookie 通常可缓解
- 短链需能访问外网；内网环境会报 `network`
- 仅处理你有权访问的内容，不绕过 DRM/付费等
- 解析依赖 yt-dlp 版本，平台变动时升级 yt-dlp 即可（`pip install -U yt-dlp`）

## 测试
- 单元测试 `tests/test_douyin.py`（mock yt-dlp/ffprobe）：路由、链接提取、probe 解析、错误分级、下载产物、Cookie 落盘受控
- 真实链接联调：需提供一条可访问的抖音链接（部分需 Cookie）
