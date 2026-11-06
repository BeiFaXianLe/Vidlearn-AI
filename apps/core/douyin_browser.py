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
    """自动探测本机 Chrome/Edge 可执行文件。

    优先 Chrome，其次 Edge；每个品牌都先把所有安装位置扫完再换品牌。
    （用户级安装的 Chrome 在 LOCALAPPDATA 下，不能因为 Program Files 里有 Edge 就提前返回。）
    """
    if os.environ.get("VIDLEARN_DOUYIN_BROWSER"):
        p = os.environ["VIDLEARN_DOUYIN_BROWSER"]
        return p if Path(p).exists() else None

    chrome: list[Path] = []
    edge: list[Path] = []
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.environ.get("LOCALAPPDATA", "")):
            if not base:
                continue
            chrome.append(Path(base) / "Google/Chrome/Application/chrome.exe")
            edge.append(Path(base) / "Microsoft/Edge/Application/msedge.exe")
    elif sys.platform == "darwin":
        chrome.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
        edge.append(Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"))
        chrome.append(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    else:
        chrome += [Path("/usr/bin/google-chrome"), Path("/usr/bin/google-chrome-stable"),
                   Path("/usr/bin/chromium"), Path("/usr/bin/chromium-browser")]
        edge.append(Path("/usr/bin/microsoft-edge"))

    for c in chrome + edge:
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
                  timeout_ms: int = 30000, profile_dir: str | None = None,
                  cookies: dict[str, str] | None = None) -> dict:
    """返回 {id,title,author,duration_ms,cover,play_urls,raw_aweme_id}。

    用干净的 headless context 解析（实测最稳）；cookies 非空时注入登录态
    （来自 CredentialProvider，经 CDP 采集）。不用浏览器桥的窗口去解析——
    桥的 profile 容易被抖音风控标记成验证中间页。
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
        # 注入已保存的抖音 Cookie（若有）
        if cookies:
            try:
                await ctx.add_cookies([
                    {"name": k, "value": v, "domain": ".douyin.com", "path": "/"}
                    for k, v in cookies.items() if k and v
                ])
            except Exception:
                pass
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


# ---------------- 收藏夹（收藏）读取通道 ----------------
#
# 抖音 web 接口（collects/list、collects/video/list）需要 a_bogus 运行时签名，
# 裸 HTTP 必被 403。这里复用浏览器通道：打开「我的收藏」页面，让真实浏览器
# 完成签名与风控，再拦截页面自己发出的这两个接口 JSON。
COLLECT_PAGE_URL = "https://www.douyin.com/user/self?showTab=collect"
_COLLECTS_LIST_API = "collects/list"
_COLLECTS_VIDEO_API = "collects/video/list"


def _first(d: dict, *keys, default=None):
    """按顺序取第一个非空字段（兼容抖音不同版本字段名）。"""
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return default


def _parse_collect_folders(payload: dict) -> list[dict]:
    """解析收藏夹（收藏合集/收藏夹）列表响应。"""
    infos = _first(payload or {}, "collects_infos", "collects", "data")
    if isinstance(infos, dict):          # 少数版本包在 data 下
        infos = _first(infos, "collects_infos", "collects", default=[])
    folders: list[dict] = []
    for f in (infos or []):
        if not isinstance(f, dict):
            continue
        cid = _first(f, "collects_id", "collect_id", "id")
        if cid in (None, ""):
            continue
        folders.append({
            "id": str(cid),
            "title": _first(f, "collects_name", "name", "title", default="未命名收藏夹"),
            "count": int(_first(f, "total_number", "count", "video_count", default=0) or 0),
            "cover": _first(f, "cover_url", "cover", default=""),
        })
    return folders


def _parse_collect_videos(payload: dict) -> dict:
    """解析收藏夹内视频列表响应，返回 {items, has_more, cursor}。

    丢弃已失效（无 aweme_id）或非视频项；避免产生半成品数据。
    """
    awemes = _first(payload or {}, "aweme_list", "awemes", "data", default=[]) or []
    items: list[dict] = []
    for a in awemes:
        if not isinstance(a, dict):
            continue
        aid = _first(a, "aweme_id", "id")
        if aid in (None, ""):
            continue
        video = a.get("video") or {}
        duration_ms = int(_first(a, "duration", default=0) or 0) or int(
            _first(video, "duration", default=0) or 0)
        cover = None
        if isinstance(video.get("cover"), dict):
            cover = (video["cover"].get("url_list") or [None])[0]
        items.append({
            "aweme_id": str(aid),
            "title": (_first(a, "desc", "title", default="") or "").strip() or "抖音视频",
            "author": ((a.get("author") or {}).get("nickname")) or "",
            "duration_ms": duration_ms,
            "cover": cover or "",
            "url": f"https://www.douyin.com/video/{aid}",
        })
    has_more = bool(_first(payload or {}, "has_more", default=False))
    cursor = _first(payload or {}, "cursor", "max_cursor", default=0)
    return {"items": items, "has_more": has_more, "cursor": int(cursor or 0)}


async def fetch_collect_folders(*, browser_path: str | None = None,
                                profile_dir: str | None = None,
                                cookies: dict[str, str] | None = None,
                                timeout_ms: int = 30000) -> dict:
    """打开「我的收藏」页面，拦截 collects/list 响应，返回 {folders, user}。

    需要登录态（profile_dir 或 cookies）；未登录/风控时抛 DouyinResolveError。
    """
    captured: dict = {}
    await _open_collect_page(
        _COLLECTS_LIST_API, COLLECT_PAGE_URL, captured,
        browser_path=browser_path, profile_dir=profile_dir,
        cookies=cookies, timeout_ms=timeout_ms)
    payload = captured.get("folders")
    if payload is None:
        raise DouyinResolveError(
            "need_login", "未读取到收藏夹列表：请先登录抖音，或稍后重试（可能被风控）")
    folders = _parse_collect_folders(payload)
    user = ""
    try:
        user = (((payload or {}).get("user") or {}).get("nickname")) or ""
    except Exception:
        user = ""
    return {"user": user, "folders": folders}


async def fetch_collect_videos(collects_id: str, *, cursor: int = 0, count: int = 20,
                               browser_path: str | None = None,
                               profile_dir: str | None = None,
                               cookies: dict[str, str] | None = None,
                               timeout_ms: int = 30000) -> dict:
    """打开某个收藏夹页面，滚动触发 collects/video/list 分页，返回指定页的
    {items, has_more, cursor}。

    抖音该接口需 a_bogus 运行时签名，无法裸 HTTP 指定 cursor 拉取；页面只在
    滚动到底部时才加载下一页。所以这里以 ``cursor`` 作为**页码游标**（0 起）：
    打开收藏夹后，逐页滚动触发「下一页」请求，截获第 ``cursor`` 页（即第
    cursor+1 次响应），返回该页内容，并把下一页页码作为新的 cursor 回传。
    ``count`` 仅作为接口分页提示，实际以抖音返回的页大小为准。
    """
    # 兼容旧约定的游标：老版本可能回传抖音原始 max_cursor（时间戳量级），
    # 无法作为页码时回退到第一页，避免把毫秒时间戳当成上千页去滚动。
    page_index = int(cursor) if isinstance(cursor, int) and 0 <= int(cursor) <= 1000 else 0
    url = (f"https://www.douyin.com/user/self?showTab=collect"
           f"&collects_id={collects_id}")
    pages = await _open_collect_videos_pages(
        url, page_index,
        browser_path=browser_path, profile_dir=profile_dir,
        cookies=cookies, timeout_ms=timeout_ms)
    if not pages:
        raise DouyinResolveError(
            "need_login", "未读取到收藏夹内容：请先登录抖音，或稍后重试（可能被风控）")
    # 目标页未到达（翻到末尾）时返回空页，避免重复返回首页导致重复追加。
    if page_index >= len(pages):
        return {"items": [], "has_more": False, "cursor": page_index}
    result = _parse_collect_videos(pages[page_index])
    # 是否还有下一页：要么已截获到更后面的页，要么本页 has_more 仍为真但还没截到后续页。
    has_more = len(pages) > page_index + 1 or bool(result.get("has_more"))
    result["has_more"] = has_more
    result["cursor"] = page_index + 1
    return result


async def _open_collect_videos_pages(page_url: str, need_index: int, *,
                                     browser_path: str | None, profile_dir: str | None,
                                     cookies: dict[str, str] | None,
                                     timeout_ms: int) -> list[dict]:
    """打开收藏夹页面，滚动触发 collects/video/list，按出现顺序返回各页 JSON。

    截获到第 ``need_index`` 页之后再尝试多截一页，用于判断是否还有下一页；
    遇到 ``has_more`` 为假或滚动无新响应即停止。返回的列表第 0 项为首屏。
    """
    if not playwright_available():
        raise DouyinResolveError("internal", "未安装 playwright")
    ensure_playwright_temp()
    from playwright.async_api import async_playwright

    pages: list[dict] = []

    def _append(data: dict) -> None:
        # 同一页可能被重复触发（例如视图重绘），按 signature 去重，避免虚增页数。
        sig = (data.get("cursor"), data.get("has_more"),
               tuple((a or {}).get("aweme_id") for a in (data.get("aweme_list") or [])[:3]))
        for existing in pages:
            esig = (existing.get("cursor"), existing.get("has_more"),
                    tuple((a or {}).get("aweme_id")
                          for a in (existing.get("aweme_list") or [])[:3]))
            if sig == esig and sig[2]:
                return
        pages.append(data)

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
        except Exception as e:  # noqa: BLE001
            raise DouyinResolveError("internal", f"启动浏览器失败：{str(e)[:120]}")
        if cookies:
            try:
                await ctx.add_cookies([
                    {"name": k, "value": v, "domain": ".douyin.com", "path": "/"}
                    for k, v in cookies.items() if k and v
                ])
            except Exception:
                pass
        page = await ctx.new_page() if not ctx.pages else ctx.pages[0]

        async def on_resp(resp):
            u = resp.url
            if _COLLECTS_VIDEO_API not in u:
                return
            try:
                if "json" not in (resp.headers.get("content-type", "") or ""):
                    return
                txt = await resp.text()
                if not txt or len(txt) < 20:
                    return
                data = json.loads(txt)
                if isinstance(data, dict):
                    _append(data)
            except Exception:
                pass

        page.on("response", on_resp)
        try:
            await page.goto(page_url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass
        steps = max(1, timeout_ms // 300)
        # 等待首屏
        for _ in range(steps):
            if pages:
                break
            await asyncio.sleep(0.3)
        # 逐页滚动直到到达 need_index 页（再多截一页判断 has_more）或到达末尾
        max_scrolls = max(need_index + 2, 3)
        for _ in range(max_scrolls):
            if len(pages) > need_index:
                # 已到达目标页；若末页 has_more 为假则无需继续
                if not bool((pages[-1] or {}).get("has_more")):
                    break
                if len(pages) > need_index + 1:
                    break
            before = len(pages)
            try:
                await page.evaluate(
                    "() => { const el = document.scrollingElement || document.documentElement;"
                    " window.scrollTo(0, el.scrollHeight);"
                    " window.dispatchEvent(new Event('scroll')); }")
            except Exception:
                pass
            # 等新页响应（最多约 steps*0.3s）
            for _ in range(max(1, steps // 2)):
                await asyncio.sleep(0.3)
                if len(pages) > before:
                    break
            if len(pages) == before:
                # 滚动后没有新响应：视为已到末尾
                if len(pages) > need_index:
                    break
                break
        try:
            await ctx.close()
            if browser is not None:
                await browser.close()
        except Exception:
            pass
    return pages


async def _open_collect_page(api_keyword: str, page_url: str, captured: dict, *,
                             browser_path: str | None, profile_dir: str | None,
                             cookies: dict[str, str] | None, timeout_ms: int) -> None:
    """打开页面并拦截指定收藏接口（api_keyword）一次响应，写入 captured。"""
    if not playwright_available():
        raise DouyinResolveError("internal", "未安装 playwright")
    ensure_playwright_temp()
    from playwright.async_api import async_playwright

    slot = "folders" if api_keyword == _COLLECTS_LIST_API else "videos"
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
        except Exception as e:  # noqa: BLE001
            raise DouyinResolveError("internal", f"启动浏览器失败：{str(e)[:120]}")
        if cookies:
            try:
                await ctx.add_cookies([
                    {"name": k, "value": v, "domain": ".douyin.com", "path": "/"}
                    for k, v in cookies.items() if k and v
                ])
            except Exception:
                pass
        page = await ctx.new_page() if not ctx.pages else ctx.pages[0]

        async def on_resp(resp):
            u = resp.url
            if api_keyword in u and slot not in captured:
                try:
                    if "json" not in (resp.headers.get("content-type", "") or ""):
                        return
                    txt = await resp.text()
                    if not txt or len(txt) < 20:
                        return
                    data = json.loads(txt)
                    if isinstance(data, dict):
                        captured[slot] = data
                except Exception:
                    pass

        page.on("response", on_resp)
        try:
            await page.goto(page_url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass
        # 等待目标接口响应；首屏偶发不触发，再刷新一次
        steps = max(1, timeout_ms // 300)
        for attempt in range(2):
            for _ in range(steps):
                if slot in captured:
                    break
                await asyncio.sleep(0.3)
            if slot in captured:
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
