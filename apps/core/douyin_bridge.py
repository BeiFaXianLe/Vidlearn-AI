"""抖音浏览器桥：用 Playwright 启动一个常驻的可交互 Chrome（带 CDP 端口）。

为什么需要它：
- 直接用 subprocess 启动 chrome.exe 在本机受限环境下会立即崩溃（0x80000003）；
- 而 Playwright 启动浏览器是正常的（已验证 Chrome 156 可正常起）。
- 这个桥进程独立于 VidLearn 服务：服务重启/退出不影响已登录的浏览器会话。

用法（由 apps/core/douyin_cdp.launch_login_browser 启动）：
    python -m apps.core.douyin_bridge --profile <dir> --port 9333
"""
from __future__ import annotations

import argparse
import asyncio
import signal
import sys

from apps.core import douyin_browser

LOGIN_URL = "https://www.douyin.com/"


async def run(profile_dir: str, port: int, url: str) -> None:
    douyin_browser.ensure_playwright_temp()
    from playwright.async_api import async_playwright

    stop = asyncio.Event()

    def _stop(*_a):  # 收到终止信号时优雅退出
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _stop)
        except (ValueError, OSError):
            pass

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            profile_dir, headless=False,
            executable_path=douyin_browser.find_chrome(),
            args=[f"--remote-debugging-port={port}",
                  "--disable-blink-features=AutomationControlled"],
            user_agent=douyin_browser.UA,
            viewport={"width": 1280, "height": 900}, locale="zh-CN")
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass
        print(f"浏览器桥就绪 profile={profile_dir} port={port}", flush=True)
        # 常驻：直到浏览器窗口被用户关闭或收到终止信号
        while not stop.is_set():
            await asyncio.sleep(1)
            try:
                if not ctx.pages:
                    break
            except Exception:
                break
        try:
            await ctx.close()
        except Exception:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--port", type=int, default=9333)
    ap.add_argument("--url", default=LOGIN_URL)
    a = ap.parse_args()
    try:
        asyncio.run(run(a.profile, a.port, a.url))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
