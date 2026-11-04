# 抖音（Douyin）支持说明

> VidLearn AI V2.2 · 浏览器解析通道（默认）+ CDP 采集登录态

## 方案总览

抖音 web 端接口（`aweme/v1/web/aweme/detail`）需要 **a_bogus 签名**，直接用 yt-dlp
或裸 HTTP 请求会被 403。实测结论：

| 路径 | 结果 |
|---|---|
| yt-dlp 内置 Douyin 解析器 | ❌ 报 `Fresh cookies needed`（其源码里也留着 "Run verification challenge code" 的 TODO），Cookie 再新鲜也救不了 |
| 裸 HTTP 直连 detail 接口 | ❌ 403（缺签名） |
| **Playwright 浏览器通道** | ✅ 稳定（让页面自己完成签名/风控，拦截 detail 响应） |

因此**默认走 Playwright 浏览器通道**：用本机 Chrome/Edge 打开视频页，页面自己完成签名/风控，
拦截 `aweme/v1/web/aweme/detail` 接口 JSON，取出标题/作者/时长/封面/播放地址并直接下载。
**公开视频无需任何 Cookie。**

## 三条通道各自的分工

1. **解析 / 下载（主路径）** —— `apps/core/douyin_browser.py`
   每次开一个**干净的 headless context**（Chrome/Edge，自动探测），拦截页面自己的 detail 响应。
   实测最稳：真实视频 → 1080x1920 / h264 / 含音频，直接落库。

2. **登录态采集（可选）** —— `apps/core/douyin_cdp.py` + `apps/core/douyin_bridge.py`
   「浏览器桥」开一个**有窗口**的 Chrome（独立 profile + CDP 调试端口），用户扫码登录一次；
   再通过 **Chrome DevTools Protocol** 让浏览器自己把 Cookie 解密交出来（绕开 SQLite 独占锁与
   Windows app-bound/v20 加密），加密存入凭据库。

3. **yt-dlp 兜底** —— 可设 `VIDLEARN_DOUYIN_USE_BROWSER=false` 关闭浏览器通道。
   注意：抖音走 yt-dlp 基本不可用（见上表），仅供 B 站等其它平台复用同一套下载管线。

### 为什么 Cookie 要用 CDP 采集，而不是读浏览器 Cookie 库

- Chromium 以**独占方式**锁住 `Cookies` SQLite：Edge/Chrome 运行时连只读都报 `WinError 32`，
  yt-dlp 的 `--cookies-from-browser` 因此报 `Could not copy Chrome cookie database`。
- 新版 Chromium/Edge 的 Cookie 用 **app-bound(v20) 加密**，外部进程解不开。
- CDP 让「浏览器进程自己解密后交出」，两个问题都不存在。
- 另：9222 端口常被其它工具占用，本项目默认用 **9333**。

### 为什么浏览器桥要绕一层 Python 进程

本机受限环境下，`subprocess` 直接启动 `chrome.exe` 会立即崩溃（`0x80000003`），
而 Playwright 启动浏览器正常。所以「浏览器桥」是一个常驻的 Python 进程（`douyin_bridge.py`），
由它用 Playwright 起浏览器。桥进程独立于 VidLearn 服务，**服务重启不影响已登录的浏览器会话**。

### 实现位置
- `apps/core/douyin_browser.py`：`resolve()`（拦截 detail）+ `download()`（流式下载）+ `find_chrome()` + `ensure_playwright_temp()`
- `apps/core/douyin_cdp.py`：`export_cookies()`（CDP 采集）+ `launch_login_browser()`（起桥）+ `to_netscape()`
- `apps/core/douyin_bridge.py`：浏览器桥进程（Playwright 启动可交互 Chrome）
- `apps/adapters/douyin.py`：浏览器优先，失败回退 yt-dlp

## 用法

导入页粘贴即可，**每行一个**：
```
https://v.douyin.com/iRxAbcDe/
https://www.douyin.com/video/7345678901234567890
7.99 复制打开抖音... https://v.douyin.com/iRxAbcDe/ 好看   ← 整段分享文案也能自动提取链接
```

## Cookie / 扫码登录（可选，部分视频或高清需要）

**设置 → 身份认证 → 抖音**（认证已从导入弹窗迁移到设置页，见 SETTINGS_AND_PROFILE.md），有三种方式：

| 操作 | 说明 |
|---|---|
| **扫码登录** | 打开一个有窗口的 Chrome（浏览器桥），在里面扫码登录抖音。登录态留在独立 profile 里，下次点击「CDP 获取」即可复用 |
| **CDP 获取** | 通过 CDP 从浏览器桥采集 Cookie（浏览器自己解密），加密存入凭据库（DPAPI，仅本机当前用户可读） |
| 手动粘贴 / 保存 | 也可直接粘贴 `ttwid; s_v_web_id; odin_tt` 等字段后保存 |

接口：
- `POST /api/credentials/douyin/login` → 起浏览器桥（返回 pid/port/profile_dir）
- `POST /api/credentials/douyin/cdp` → 采集 Cookie 并落库（返回 count/keys）
- `POST /api/credentials/verify` `{platform:"douyin"}` → 字段体检（查 ttwid/msToken/sessionid）

> 依赖：`playwright` + 本机 Chrome/Edge（自动探测；优先 Chrome，其次 Edge）。

## 字幕
抖音一般无平台字幕 → 自动走**本地 ASR**（faster-whisper），再经「字幕校准」纠正同音错字。

## 已知限制 / 风险
- 抖音反爬较强，**可能间歇性返回验证中间页 / 风控**（错误码 `blocked`，可重试）；换网络通常可缓解
- **被风控标记的 profile 解析会失败**：`resolve()` 每次都开干净 context 正是为了避开这点；
  不要用浏览器桥的窗口去抓视频
- 注入登录态 Cookie 到解析 context 未必更好（风控标记会跟着 cookie 走），默认不注入
- 短链需能访问外网；内网环境会报 `network`
- 仅处理你有权访问的内容，不绕过 DRM/付费等

## 测试
- `tests/test_douyin.py`（mock yt-dlp/ffprobe/浏览器）：路由、链接提取、probe 解析、错误分级、下载产物、Cookie 落盘受控
- `tests/test_douyin_cdp.py`：Cookie 域过滤（排除其它站点会话）、Netscape 格式（会话 cookie 写 0、跳过空名）、
  端口探测、CDP/登录两个接口、verify 参数回归
- 真实联调：`api/probe` + `api/import` 已在真实抖音视频上验证（1080x1920 / h264 / 含音频）

## 环境注意事项（排查用）
- `%TEMP%` 不可写（沙箱/受限环境）时 Playwright 会卡在 `mkdtemp` —— `ensure_playwright_temp()`
  会探测并改指向项目内 `.tmp/pwtmp`
- 浏览器桥日志：`data/browsers/bridge-<port>.log`
- `find_chrome()` 会扫 `Program Files` / `Program Files (x86)` / `LOCALAPPDATA`，
  **Chrome 优先于 Edge**（用户级安装的 Chrome 在 `LOCALAPPDATA` 下）
