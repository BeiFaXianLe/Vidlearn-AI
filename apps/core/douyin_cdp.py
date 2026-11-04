"""抖音 CDP 通道：通过 Chrome DevTools Protocol 采集 Cookie / 维护带登录态的浏览器。

为什么不用「直接读浏览器 Cookie 库」或 yt-dlp 的 --cookies-from-browser：
- Chromium 以独占方式锁住 Cookies SQLite（Edge 运行中连只读都报 WinError 32），
  yt-dlp 因此报 "Could not copy Chrome cookie database"。
- 新版 Chromium/Edge 的 Cookie 用 app-bound(v20) 加密，外部进程解不开。
- CDP 让「浏览器进程自己解密后再交出」，上面两个问题都不存在。

但要清醒：Cookie 只是副产品。抖音 web 接口需要 a_bogus 签名，
yt-dlp 的 DouyinIE 直连 aweme/v1/web/aweme/detail 会被 403（其源码里同样留着
"Run verification challenge code to generate signature cookies" 的 TODO）。
所以真正稳定的是**浏览器通道**：让真实浏览器发请求，签名与风控由页面自己完成。
CDP 在这里的价值是给浏览器通道提供**带登录态的持久化 profile**（扫码登录一次，长期复用）。

实测结论（本机 Edge 152 + 抖音）：
- CDP 导出 cookie：可用，一次拿到 30+ 条（含 ttwid / s_v_web_id / odin_tt）
- 导出后直打 detail 接口：403（缺签名，与 cookie 新鲜度无关）
- 项目浏览器通道（Playwright 拦截页面自己的 detail 响应）：真实视频解析成功
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

# 9222 常被其它工具占用（本机 WorkBuddy 内置 Chromium 就占着），默认走 9333
DEFAULT_PORT = 9333

# 只采集抖音相关域，避免把用户其它站点的会话一起带出去
WANT_DOMAINS = ("douyin.com", "ttwid.cn", "iesdouyin.com")

LOGIN_URL = "https://www.douyin.com/"


class DouyinCDPError(Exception):
    """CDP 通道错误。"""


def cdp_endpoint(port: int | None = None) -> str:
    return f"http://127.0.0.1:{port or DEFAULT_PORT}"


def cdp_available(port: int | None = None, timeout: float = 2.0) -> bool:
    """调试端口是否已有浏览器在监听。"""
    try:
        with urllib.request.urlopen(f"{cdp_endpoint(port)}/json/version", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _filter(cookies: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for c in cookies:
        name = (c.get("name") or "").strip()
        domain = c.get("domain") or ""
        if not name or not any(w in domain for w in WANT_DOMAINS):
            continue
        out[name] = c.get("value") or ""
    return out


async def export_cookies(port: int | None = None) -> dict[str, str]:
    """从已开启调试端口的浏览器导出抖音 Cookie（浏览器自己解密）。"""
    if not cdp_available(port):
        raise DouyinCDPError(
            f"没有浏览器在 {cdp_endpoint(port)} 提供调试端口，"
            f"请先点「扫码登录」或用带 --remote-debugging-port 的浏览器打开抖音")
    try:
        from playwright.async_api import async_playwright
    except Exception as e:  # noqa: BLE001
        raise DouyinCDPError(f"未安装 playwright：{e}") from e
    from apps.core import douyin_browser
    douyin_browser.ensure_playwright_temp()

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_endpoint(port))
        try:
            merged: list[dict] = []
            for ctx in browser.contexts:
                merged.extend(await ctx.cookies())
        finally:
            await browser.close()
    return _filter(merged)


async def export_cookies_via_profile(profile_dir: str, port: int | None = None) -> dict[str, str]:
    """用持久化 profile 起一个临时浏览器访问抖音，取 cookie 后关闭（不打扰已有实例）。"""
    try:
        from playwright.async_api import async_playwright
    except Exception as e:  # noqa: BLE001
        raise DouyinCDPError(f"未安装 playwright：{e}") from e
    from apps.core import douyin_browser
    douyin_browser.ensure_playwright_temp()

    path = Path(profile_dir)
    path.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        kwargs = {"headless": True,
                  "args": ["--disable-blink-features=AutomationControlled",
                           "--disable-dev-shm-usage"]}
        bp = douyin_browser.find_chrome()
        if bp:
            kwargs["executable_path"] = bp
        try:
            ctx = await p.chromium.launch_persistent_context(str(path), **kwargs)
        except Exception as e:  # noqa: BLE001
            raise DouyinCDPError(f"启动浏览器失败：{str(e)[:120]}") from e
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(6000)
            cookies = await ctx.cookies()
        finally:
            await ctx.close()
    return _filter(cookies)


def launch_login_browser(profile_dir: str, port: int | None = None,
                         url: str = LOGIN_URL) -> int:
    """启动「浏览器桥」：一个常驻的可交互 Chrome 窗口（带 CDP 端口），供用户扫码登录。

    为什么绕一层 Python 桥进程而不是直接起 chrome.exe：
    本机受限环境下 subprocess 直接启动 chrome.exe 会立即崩溃（0x80000003），
    而 Playwright 启动浏览器正常。桥进程独立于 VidLearn 服务，服务重启不影响登录态。

    返回桥进程 PID；用 close_login_browser(pid) 关闭。
    """
    from apps.core import douyin_browser

    if not douyin_browser.find_chrome():
        raise DouyinCDPError("未找到本机 Chrome/Edge 可执行文件")
    port = port or DEFAULT_PORT
    path = Path(profile_dir)
    path.mkdir(parents=True, exist_ok=True)
    bridge_log = path.parent / f"bridge-{port}.log"
    try:
        bridge_log.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    args = [sys.executable, "-m", "apps.core.douyin_bridge",
            "--profile", str(path), "--port", str(port), "--url", url]
    flags = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | \
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    try:
        log = open(bridge_log, "ab")
    except OSError:
        log = subprocess.DEVNULL
    proc = subprocess.Popen(args, cwd=str(Path(__file__).resolve().parents[2]),
                            stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                            creationflags=flags, close_fds=True)
    return proc.pid


def close_login_browser(pid: int) -> None:
    """关闭浏览器桥进程（及其浏览器）。"""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, check=False)
        else:
            os.kill(pid, 15)
    except Exception:
        pass


def cookie_header(cookies: dict[str, str]) -> str:
    """转成 Cookie 请求头字符串。"""
    return "; ".join(f"{k}={v}" for k, v in cookies.items() if k)


def to_netscape(cookies: list[dict]) -> str:
    """CDP cookie 列表 -> Netscape cookie 文件内容（yt-dlp 可直接 --cookies 使用）。"""
    lines = ["# Netscape HTTP Cookie File", "# generated by VidLearn AI (CDP)"]
    for c in cookies:
        name = (c.get("name") or "").strip()
        if not name:
            continue
        domain = c.get("domain") or ""
        exp = int(c.get("expires") or 0)
        if exp <= 0:                       # 会话 cookie：0=会话（-1 会被 yt-dlp 判非法）
            exp = 0
        lines.append("\t".join([
            domain,
            "TRUE" if domain.startswith(".") else "FALSE",
            c.get("path") or "/",
            "TRUE" if c.get("secure") else "FALSE",
            str(exp),
            name,
            c.get("value") or "",
        ]))
    return "\n".join(lines) + "\n"
