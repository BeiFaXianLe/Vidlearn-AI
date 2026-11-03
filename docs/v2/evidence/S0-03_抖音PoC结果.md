# S0-03 抖音下载 PoC 执行结果（D05 强门禁）

- 日期：2026-11-02
- 对象：`jiji262/douyin-downloader`（D03 冻结方案，MIT，12.5k★）
- 环境：Windows / Python 3.12.13 / 依赖已安装（aiohttp / httpx / gmssl 等）
- 方式：匿名、未使用 Cookie、未绕过任何访问控制
- 结论：**不通过（FAIL）→ 触发 D05 强门禁**

---

## 一、实测证据（A 级）

### 1. 直接调用其内部 API 客户端（匿名 + CLI 默认路径）

```
DouyinAPIClient(cookies={}, page_bridge=None).get_video_detail(aweme_id)
→ HTTP 403
→ body: "Blocked by ArgusSecurityPlugin Uifid Not Found"
→ path: /aweme/v1/web/aweme/detail/
→ 返回 None（错误被静默吞掉）
```

### 2. 项目自身文档的明确说明（B 级，源码文档）

`AGENTS.md`（作者维护）原文：

> Douyin's `ArgusSecurityPlugin` 403s non-page requests to `aweme/favorite`... `aweme/detail`, `aweme/post`, `mix/detail`... (since 2026-09-14). Desktop signs them inside its hidden login window; **the CLI always runs `DouyinAPIClient(page_bridge=None)`, so `_request_json_gated` falls back to aiohttp and these downloads cannot work in the CLI**.

`README.md` 原文：

> Douyin's request verification currently blocks CLI downloads of individual videos/photos... **Refreshing cookies or retrying does not fix this verification block.**

### 3. 上游最新版本核查

| 项 | 值 |
|---|---|
| 最新 release | `desktop-v0.12.5`（2026-10-08） |
| 产物 | 只有桌面安装包（`.exe` / `.dmg`），**无 CLI 能力更新** |
| 桌面包特征 | 未签名、含 `version-policy.json`、签名校验、内测资格限制 |

结论：作者已把可用的抖音下载能力**收进闭源桌面版**，开源 CLI 仅保留受限能力。

---

## 二、结论判定

| D05 验证项 | 结果 |
|---|---|
| 短链解析 | ❌ 未到解析即被 403 |
| 长链解析 | ❌ 403 |
| 元数据获取 | ❌ 403 |
| 实际视频下载 | ❌ 不可达 |
| FFprobe 校验 | ⛔ 无产物可校验 |
| 匿名模式 | ❌ 不可用 |
| Cookie 必要性 | ❌ **加 Cookie 也无效**（作者明示 + 实测门禁） |
| 依赖/许可证/稳定性 | ✅ MIT、依赖正常（唯一通过项） |

**判定：不通过。** 这不是配置问题，而是抖音 2026-09 起的风控（ArgusSecurityPlugin）对非页面请求的确定性拦截。

---

## 三、对 V2.0 计划的影响

按 PRD V2.0 §3.3「(上线门禁) PoC 不通过，不得将抖音下载能力标记为正式可用」，因此：

1. **抖音不得标记为正式可用**。
2. 需在 S2 保留 `DouyinAdapter` 接口 + 明确降级提示（"该平台当前受限，请使用本地文件导入"）。
3. 抖音实现从 S2 主体工作中移除，节省约 3–4 人日。

---

## 四、可选替代路线（需你决策）

| 路线 | 说明 | 合规 | 工程成本 |
|---|---|---|---|
| A. 不实现抖音下载 | 只保留入口 + 降级提示，引导本地文件 | ✅ 无风险 | 最低 |
| B. 集成桌面版 Douzy | 用其闭源桌面二进制，VidLearn 无法程序化调用 | ⚠️ 未签名/受限 | 高且不可控 |
| C. 换 `Evil0ctal/Douyin_TikTok_Download_API`（21k★, Apache-2.0） | 自建游客身份池，理论上可绕过当前风控 | ⚠️ 明确承认违反平台条款 | 高（Docker+PG+Redis），且随时可能失效 |
| D. 用户手动提供已下载文件 | 用户自己下载后导入 VidLearn 处理 | ✅ 无风险 | 最低 |

> 我的建议：**A + D**。抖音链接导入保留 UI，失败时明确提示并引导本地文件。

---

## 四之二、补充实测：页面上下文路线（B'）是否可行

为回答「抖音是否完全行不通」，额外用 Playwright + 系统 Chrome 做了页面上下文探测（未登录、只读、单条）：

| 探测 | 结果 |
|---|---|
| 打开 `douyin.com` | ✅ 200，标题「抖音-记录美好生活」 |
| 页面自动获得的 cookie | ✅ `ttwid`、`s_v_web_id`、`__ac_nonce`、`__ac_signature` |
| **页面内 fetch `aweme/detail`** | ✅ **HTTP 200**（不再是 403！） |
| 首页推荐流 `aweme_list` | ⚠️ 未返回（未登录态推荐流被降级） |
| 搜索结果页 | ⚠️ 未能加载（疑似触发验证） |

**关键结论**：
1. **抖音并非完全死路**——`ArgusSecurityPlugin` 的 403 只针对"非页面上下文"请求；在真实浏览器页面里发请求，**拦截消失（200）**。
2. 这也正是闭源桌面版 Douzy 的做法：在隐藏登录窗口内用页面 SDK 补 `uifid`/签名。
3. 但「匿名未登录」下，推荐流/搜索等数据面仍被降级，**要稳定拿到指定视频数据，基本需要登录态 + 页面内签名**。

因此准确表述是：

> **"jiji262 CLI/子进程方案" 行不通；但"抖音下载"本身可行，前提是走浏览器页面上下文，且大概率需要登录态。**

对应的工程路线（需你决策）：

| 路线 | 可行性 | 说明 |
|---|---|---|
| **B'. VidLearn 内嵌 Playwright 页面上下文抓取** | ⚠️ 中 | 我们自己在 App 内起一个隐藏浏览器会话（可复用系统 Chrome，无需下载内核），登录后抓取。工程量大，且随抖音改版需长期维护 |
| C. 接 Evil0ctal 自建身份池 | ⚠️ 中 | 别人已把"页面/签名"这层做成服务，但需 Docker+PG+Redis 且违条款风险 |
| A+D. 入口 + 本地文件兜底 | ✅ 高 | 零风险，最快 |

---

## 五、复现方法

```powershell
# 1. 获取源码（git clone 在本机被网络中断，改用 tarball）
#    https://codeload.github.com/jiji262/douyin-downloader/tar.gz/refs/heads/main
# 2. 安装依赖
uv pip install -r requirements.txt
# 3. 匿名调用详情接口（page_bridge=None 即 CLI 真实路径）
#    结果：HTTP 403  Blocked by ArgusSecurityPlugin Uifid Not Found
```

源码保留在 `.tmp/poc/douyin-downloader-main/`（约 3.3MB，可随时清理）。
