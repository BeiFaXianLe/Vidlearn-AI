"""抖音 Playwright 解析通道（免 Cookie 优先）。

思路：用真实浏览器打开抖音分享页/视频页，让页面自己完成签名与风控，
再拦截它的 `aweme/v1/web/aweme/detail` 接口 JSON，取出标题/作者/时长/封面/播放地址，
最后由本模块直接下载媒体。相比 yt-dlp 的 Douyin extractor（当前普遍卡在
"Fresh cookies needed"），这条通道更稳，且多数视频**无需手动准备 Cookie**。

依赖：playwright（可选）。浏览器优先用本机 Chrome，其次用 playwright 自带 chromium。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.request
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")

# Playwright 临时目录探测结果缓存（进程内只探一次）
_TEMP_STATE: dict = {}


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def _temp_writable(path: str, timeout: float = 1.5) -> bool:
    """探测目录是否可写。

    受限环境（如服务跑在沙箱里）下，写 %TEMP% 是被**无限挂起**而不是报错，
    而 os.access 仍返回 True —— 所以必须用线程 + 超时来试写。
    """
    import tempfile
    import threading

    state: dict = {}

    def _w() -> None:
        try:
            with tempfile.NamedTemporaryFile(dir=path, prefix="probe_"):
                state["ok"] = True
        except Exception:
            state["ok"] = False

    t = threading.Thread(target=_w, daemon=True)
    t.start()
    t.join(timeout)
    return bool(state.get("ok"))


def ensure_playwright_temp() -> str | None:
    """确保 Playwright 有可写的临时目录。

    Playwright 会在 mkdtemp('...playwright-artifacts-XXXXXX') 建目录，
    %TEMP% 不可写时直接失败（受限环境里表现为挂起）。这里把 TEMP/TMP
    改指向项目内 .tmp/pwtmp（driver 继承环境变量），保证浏览器通道可用。
    """
    if "dir" in _TEMP_STATE:
        return _TEMP_STATE["dir"]
    for key in ("TEMP", "TMP"):
        d = os.environ.get(key)
        if d and os.path.isdir(d) and _temp_writable(d):
            _TEMP_STATE["dir"] = None
            return None
    root = Path(__file__).resolve().parents[2] / ".tmp" / "pwtmp"
    try:
        root.mkdir(parents=True, exist_ok=True)
        os.environ["TEMP"] = str(root)
        os.environ["TMP"] = str(root)
        _TEMP_STATE["dir"] = str(root)
        return str(root)
    except OSError:
        _TEMP_STATE["dir"] = None
        return None


def find_chrome() -> str | None:
    """自动探测本机 Chrome/Edge 可执行文件。"""
    if os.environ.get("VIDLEARN_DOUYIN_BROWSER"):
        p = os.environ["VIDLEARN_DOUYIN_BROWSER"]
        return p if Path(p).exists() else None
    cands = []
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.environ.get("LOCALAPPDATA", "")):
            if not base:
                continue
            cands += [
                Path(base) / "Google/Chrome/Application/chrome.exe",
                Path(base) / "Microsoft/Edge/Application/msedge.exe",
            ]
    elif sys.platform == "darwin":
        cands += [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                  Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")]
    else:
        cands += [Path("/usr/bin/google-chrome"), Path("/usr/bin/chromium"),
                  Path("/usr/bin/chromium-browser"), Path("/usr/bin/microsoft-edge")]
    for c in cands:
        if c.exists():
            return str(c)
    return None


class DouyinResolveError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind          # need_login / blocked / not_found / internal
        self.message = message


def _pick_play_urls(video: dict) -> list[str]:
    """从 video 节点里收集播放地址（优先无水印 H264）。"""
    urls: list[str] = []
    for key in ("play_addr_h264", "play_addr", "download_addr", "play_addr_265"):
        pa = video.get(key) or {}
        for u in (pa.get("url_list") or []):
            if u and u not in urls:
                urls.append(u)
    for br in (video.get("bit_rate") or []):
        pa = br.get("play_addr") or {}
        for u in (pa.get("url_list") or []):
            if u and u not in urls:
                urls.append(u)
    return urls


async def resolve(url: str, *, browser_path: str | None = None,
                  timeout_ms: int = 30000, profile_dir: str | None = None) -> dict:
    """返回 {id,title,author,duration_ms,cover,play_urls,raw_aweme_id}。

    profile_dir 非空时使用持久化 profile（同一目录复用登录态，扫码登录一次长期有效）。
    """
    if not playwright_available():
        raise DouyinResolveError("internal", "未安装 playwright")
    ensure_playwright_temp()
    from playwright.async_api import async_playwright

    captured: dict = {}
    async with async_playwright() as p:
        launch_options = {"headless": True,
                          "args": ["--disable-blink-features=AutomationControlled",
                                   "--disable-dev-shm-usage"]}
        ctx_options = {"user_agent": UA, "viewport": {"width": 1280, "height": 900},
                       "locale": "zh-CN"}
        bp = browser_path or find_chrome()
        if bp:
            launch_options["executable_path"] = bp
        browser = None
        try:
            if profile_dir:
                Path(profile_dir).mkdir(parents=True, exist_ok=True)
                ctx = await p.chromium.launch_persistent_context(
                    str(profile_dir), **launch_options, **ctx_options)
            else:
                browser = await p.chromium.launch(**launch_options)
                ctx = await browser.new_context(**ctx_options)
        except Exception as e:
            raise DouyinResolveError("internal", f"启动浏览器失败：{str(e)[:120]}")
        page = await ctx.new_page() if not ctx.pages else ctx.pages[0]

        async def on_resp(resp):
            u = resp.url
            if "aweme/detail" in u or "aweme/v1/web/aweme/detail" in u:
                try:
                    if "json" not in (resp.headers.get("content-type", "") or ""):
                        return
                    txt = await resp.text()
                    if not txt or len(txt) < 300:
                        return
                    data = json.loads(txt)
                    d = data.get("aweme_detail")
                    if d and "detail" not in captured:
                        captured["detail"] = d
                except Exception:
                    pass

        page.on("response", on_resp)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass
        # 等待 detail 响应；未拿到则刷新一次再等（抖音首屏偶发不触发接口）
        steps = max(1, timeout_ms // 300)
        for attempt in range(2):
            for _ in range(steps):
                if "detail" in captured:
                    break
                await asyncio.sleep(0.3)
            if "detail" in captured:
                break
            if attempt == 0:
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
                except Exception:
                    pass
        try:
            await ctx.close()
            if browser is not None:
                await browser.close()
        except Exception:
            pass

    d = captured.get("detail")
    if not d:
        raise DouyinResolveError("blocked", "未获取到视频信息（可能需要登录/被风控/链接失效）")
    v = d.get("video") or {}
    play_urls = _pick_play_urls(v)
    if not play_urls:
        raise DouyinResolveError("blocked", "未解析到播放地址（可能需要登录）")
    cover = (((v.get("cover") or {}).get("url_list")) or [None])[0]
    return {
        "id": str(d.get("aweme_id") or d.get("id") or ""),
        "title": (d.get("desc") or "抖音视频").strip() or "抖音视频",
        "author": ((d.get("author") or {}).get("nickname")),
        "duration_ms": int(d.get("duration") or 0),
        "cover": cover,
        "play_urls": play_urls,
    }


def download(play_urls: list[str], out_path: Path, *, timeout: int = 120) -> Path:
    """按候选地址依次尝试，流式下载到 out_path。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    last_err = None
    for u in play_urls:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": UA,
                                                     "Referer": "https://www.douyin.com/"})
            with urllib.request.urlopen(req, timeout=timeout) as r, open(out_path, "wb") as f:
                while True:
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
            if out_path.stat().st_size > 10 * 1024:
                return out_path
        except Exception as e:  # noqa: BLE001
            last_err = e
            try:
                if out_path.exists():
                    out_path.unlink()
            except OSError:
                pass
    raise DouyinResolveError("internal", f"下载播放地址失败：{str(last_err)[:120]}")
