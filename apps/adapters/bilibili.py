"""Bilibili 适配器（S2-03 匿名 / S2-04 登录 / S2-05 平台字幕）。

要点（全部来自 S0 实测）：
- 下载走 yt-dlp，参数数组调用，绝不拼 shell。
- 登录态用 CredentialProvider 提供的 cookie（转 Netscape cookie 文件供 yt-dlp 使用）。
- 平台字幕：每次重新请求 /x/player/v2 拿新 auth_key；时间戳强校验，超时长则重取。
- 错误分级：need_login / format_changed / not_authorized / network ...
"""
from __future__ import annotations

import json
import re
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from apps.adapters._util import ffprobe_json, run_cmd, sha256_file
from apps.adapters.base import (
    AcquireError,
    ErrorCode,
    FetchOpts,
    MediaResult,
    VideoMeta,
)

BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")
API_HEADERS = {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}

# 收藏夹相关接口（需登录态 Cookie）
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
FAV_FOLDER_URL = "https://api.bilibili.com/x/v3/fav/folder/created/list-all"
FAV_RESOURCE_URL = "https://api.bilibili.com/x/v3/fav/resource/list"


def _safe_unlink(p: Path | None, attempts: int = 15) -> None:
    """Windows 下子进程可能短暂占用文件，重试删除；失败不抛。"""
    if not p:
        return
    import time
    for _ in range(attempts):
        try:
            if Path(p).exists():
                Path(p).unlink()
            return
        except (PermissionError, OSError):
            time.sleep(0.2)


class BilibiliAdapter:
    name = "bilibili"

    def __init__(self, yt_dlp_path: str = "yt-dlp", ffprobe: str = "ffprobe",
                 cookie_provider=None, tolerance_ms: int = 2000,
                 refetch_attempts: int = 3, cookie_tmp_dir=None):
        self._ytdlp = yt_dlp_path
        self._ffprobe = ffprobe
        self._cookies = cookie_provider  # CredentialProvider | None
        self._tol = tolerance_ms
        self._attempts = refetch_attempts
        # Cookie 临时文件固定落在受控目录（绝不写当前工作目录），
        # 避免凭证泄漏到项目根目录。默认放系统临时目录下的专用子目录。
        if cookie_tmp_dir:
            self._cookie_dir = Path(cookie_tmp_dir)
        else:
            # 注意：沙箱/受限环境下 tempfile.gettempdir() 与系统 TEMP 可能不可写，
            # 甚至回落到当前工作目录（会把凭证泄漏到项目根）。统一放到项目内
            # 被 gitignore 的 .tmp/cookies 下，确保可写且不污染仓库。
            _root = Path(__file__).resolve().parents[2]
            self._cookie_dir = _root / ".tmp" / "cookies"
        self._cookie_dir.mkdir(parents=True, exist_ok=True)

    def _new_cookie_file(self) -> Path:
        """生成本次调用专用的 cookie 文件路径（唯一名）。"""
        import uuid
        self._cookie_dir.mkdir(parents=True, exist_ok=True)
        return self._cookie_dir / f"cookie_{uuid.uuid4().hex[:12]}.txt"

    @staticmethod
    def purge_stale_cookie_files(cookie_dir, older_than_sec: int = 3600) -> int:
        """清理残留的 cookie 临时文件（超过阈值时长）。返回删除数量。"""
        import time
        d = Path(cookie_dir)
        if not d.exists():
            return 0
        now = time.time()
        n = 0
        for f in d.glob("cookie_*.txt"):
            try:
                if older_than_sec <= 0 or now - f.stat().st_mtime > older_than_sec:
                    f.unlink()
                    n += 1
            except OSError:
                pass
        return n

    # ---------- 基础 ----------
    async def can_handle(self, url: str) -> bool:
        return "bilibili.com" in url or bool(BV_RE.search(url))

    def _cookie_header(self) -> str | None:
        if not self._cookies:
            return None
        c = self._cookies.get("bilibili")
        if not c:
            return None
        return "; ".join(f"{k}={v}" for k, v in c.items())

    def _write_cookie_file(self, path: Path) -> bool:
        ck = self._cookie_header()
        if not ck:
            return False
        lines = ["# Netscape HTTP Cookie File"]
        for kv in ck.split("; "):
            if "=" not in kv:
                continue
            k, v = kv.split("=", 1)
            lines.append("\t".join([".bilibili.com", "TRUE", "/", "FALSE", "0", k, v]))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True

    # ---------- 探测 ----------
    async def probe(self, url: str) -> VideoMeta:
        args = [self._ytdlp, "--simulate", "--dump-single-json", "--no-warnings", "--no-playlist"]
        tmp_cookie = None
        ck = self._cookie_header()
        if ck:
            tmp_cookie = self._new_cookie_file()
            self._write_cookie_file(tmp_cookie)
            args += ["--cookies", str(tmp_cookie)]
        args.append(url)
        try:
            rc, out, err = await run_cmd(args, timeout=120)
        finally:
            _safe_unlink(tmp_cookie)
        if rc != 0:
            raise self._classify(err, out)
        try:
            d = json.loads(out)
        except json.JSONDecodeError:
            raise AcquireError(ErrorCode.FORMAT_CHANGED, "yt-dlp 输出非 JSON", retryable=True)
        fmts = d.get("formats") or []
        heights = sorted({f.get("height") for f in fmts if f.get("height")}, reverse=True)
        return VideoMeta(
            platform="bilibili",
            platform_video_id=d.get("id") or "",
            title=d.get("title") or "",
            author=d.get("uploader"),
            duration_ms=int((d.get("duration") or 0) * 1000),
            cover_url=d.get("thumbnail"),
            available_heights=heights,
            has_subtitle_tracks=bool(d.get("subtitles") or d.get("automatic_captions")),
            source_url=d.get("webpage_url") or url,
            extra={"extractor": d.get("extractor")},
        )

    # ---------- 下载 ----------
    async def fetch_media(self, url: str, opts: FetchOpts) -> MediaResult:
        out_dir = Path(opts.out_dir or ".")
        out_dir.mkdir(parents=True, exist_ok=True)
        outtmpl = str(out_dir / "%(id)s.%(ext)s")

        args = [self._ytdlp, "--no-warnings", "--no-playlist",
                "--merge-output-format", "mp4", "-o", outtmpl,
                "--continue",              # 断点续传：复用 .part，重试不再从 0 开始
                "--socket-timeout", "20",  # 空闲连接 20s 自动重连，避免假死
                "--retries", "10",
                "--fragment-retries", "10",
                "--concurrent-fragments", "4"]  # 多连接：更快，单连接假死不致命
        if opts.download_sections:
            args += ["--download-sections", opts.download_sections]
        # 格式选择
        if opts.audio_only:
            args += ["-f", "bestaudio/best"]
        else:
            # 明确优先 H.264(avc1)，避开 av01/hevc（浏览器兼容差）；
            # 依次回退：avc1+ba → 任意 bv*+ba → best
            h = f"[height<={opts.max_height}]" if opts.max_height else ""
            args += ["-f",
                     f"bv*{h}[vcodec^=avc1]+ba/bv*{h}+ba/bv*+ba/best"]
        tmp_cookie = None
        if self._cookie_header():
            tmp_cookie = self._new_cookie_file()
            self._write_cookie_file(tmp_cookie)
            args += ["--cookies", str(tmp_cookie)]
        args.append(url)
        try:
            rc, out, err = await run_cmd(args, timeout=opts.timeout_sec)
        finally:
            _safe_unlink(tmp_cookie)
        if rc != 0:
            raise self._classify(err, out)

        # 找到产物
        files = sorted(out_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
        media = [f for f in files if f.is_file() and f.suffix.lower() in
                 (".mp4", ".mkv", ".webm", ".m4a", ".mp3", ".aac")]
        if not media:
            raise AcquireError(ErrorCode.MEDIA_INVALID, "下载完成但未找到媒体文件")
        target = media[0]

        info = await ffprobe_json(target, self._ffprobe)
        if info is None:
            raise AcquireError(ErrorCode.MEDIA_INVALID, "下载产物 FFprobe 无法解析")
        fmt = info.get("format") or {}
        streams = info.get("streams") or []
        v = [s for s in streams if s.get("codec_type") == "video"]
        a = [s for s in streams if s.get("codec_type") == "audio"]
        return MediaResult(
            file_path=target,
            container=fmt.get("format_name") or "unknown",
            sha256=sha256_file(target),
            declared_duration_ms=int(float(fmt.get("duration") or 0) * 1000),
            width=v[0].get("width") if v else None,
            height=v[0].get("height") if v else None,
            vcodec=v[0].get("codec_name") if v else None,
            acodec=a[0].get("codec_name") if a else None,
            has_audio=bool(a),
        )

    # ---------- 平台字幕（S2-05） ----------
    async def fetch_subtitles(self, url: str) -> dict:
        """获取平台字幕，含 S0 实测的强校验与重取。

        返回 {"tracks": [...], "chosen": {lang, source, cues:[{start_ms,end_ms,text}], duration_ms}}
        全部失败返回 {"tracks": [], "chosen": None, "reason": ...}
        """
        bvid = BV_RE.search(url).group(1) if BV_RE.search(url) else None
        if not bvid:
            return {"tracks": [], "chosen": None, "reason": "无法解析 BV 号"}

        cookie = self._cookie_header()
        view = await self._api_get(
            f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}", cookie)
        if not view or view.get("code") != 0:
            return {"tracks": [], "chosen": None, "reason": "view 接口失败"}
        data = view["data"]
        aid, cid = data.get("aid"), data.get("cid")
        duration_ms = int(float(data.get("duration") or 0) * 1000)

        tracks: list[dict] = []
        for _ in range(self._attempts):
            p = await self._api_get(
                f"https://api.bilibili.com/x/player/v2?aid={aid}&cid={cid}", cookie)
            subs = (((p or {}).get("data") or {}).get("subtitle") or {}).get("subtitles") or []
            if not subs:
                break
            tracks = subs
            picked = await self._pick_valid_cue(subs, duration_ms, cookie)
            if picked:
                picked["duration_ms"] = duration_ms
                return {"tracks": tracks, "chosen": picked}
        # 全部失败
        return {"tracks": tracks, "chosen": None,
                "reason": "字幕时间戳校验未通过或 auth_key 失效"}

    async def _pick_valid_cue(self, subs: list[dict], duration_ms: int, cookie,
                              title: str | None = None) -> dict | None:
        for s in subs:
            u = s.get("subtitle_url") or ""
            if not u:
                continue
            if u.startswith("//"):
                u = "https:" + u
            body = await self._api_get(u, None)
            cues = (body or {}).get("body") or []
            if not cues:
                continue
            last_ms = int(float(cues[-1]["to"]) * 1000)
            if last_ms > duration_ms + self._tol:
                continue  # 污染，换下一个/下一轮
            norm = [{"start_ms": int(float(c["from"]) * 1000),
                     "end_ms": int(float(c["to"]) * 1000),
                     "text": c.get("content", "")} for c in cues]
            # 覆盖率校验：字幕应覆盖相当比例时长（防"只有几分钟的片段"被当全文）
            covered = norm[-1]["end_ms"] - norm[0]["start_ms"]
            if duration_ms and covered < duration_ms * 0.5:
                continue
            return {
                "lang": s.get("lan"),
                "is_ai": bool(s.get("ai_type") == 0),
                "source": "bilibili_ai" if s.get("ai_type") == 0 else "bilibili_human",
                "cues": norm,
                "coverage_ratio": round(covered / duration_ms, 3) if duration_ms else None,
            }
        return None

    async def _api_get(self, url: str, cookie: str | None) -> dict | None:
        headers = dict(API_HEADERS)
        if cookie:
            headers["Cookie"] = cookie
        try:
            req = urllib.request.Request(url, headers=headers)
            raw = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")
            return json.loads(raw) if raw.strip() else None
        except Exception:
            return None

    async def verify_login(self) -> dict:
        """检测当前 Cookie 是否为有效登录态：返回 {ok, uname, mid, message}。"""
        cookie = self._cookie_header()
        if not cookie:
            return {"ok": False, "message": "未配置 Cookie"}
        nav = await self._api_get(NAV_URL, cookie)
        if not nav or nav.get("code") != 0:
            return {"ok": False, "message": "Cookie 无效或已过期"}
        data = nav.get("data") or {}
        if not data.get("isLogin"):
            return {"ok": False, "message": "Cookie 未登录（缺 SESSDATA）"}
        return {"ok": True, "uname": data.get("uname"), "mid": data.get("mid"),
                "message": "登录有效"}

    # ---------- 收藏夹读取（S2 增强：登录态） ----------
    async def fetch_fav_folders(self) -> dict:
        """读取当前登录账号的收藏夹文件夹列表。

        需要有效 Cookie（SESSDATA）。返回：
        {"mid": int, "uname": str, "folders": [{"id","title","count"}]}
        """
        cookie = self._cookie_header()
        if not cookie:
            raise AcquireError(ErrorCode.NEED_LOGIN, "未配置 Cookie，无法读取收藏夹")

        nav = await self._api_get(NAV_URL, cookie)
        if not nav or nav.get("code") != 0:
            raise AcquireError(ErrorCode.NEED_LOGIN, "Cookie 无效或已过期，请重新登录")
        info = nav.get("data") or {}
        if not info.get("isLogin"):
            raise AcquireError(ErrorCode.NEED_LOGIN, "未登录：Cookie 缺少有效 SESSDATA")
        mid = info.get("mid")

        r = await self._api_get(f"{FAV_FOLDER_URL}?up_mid={mid}&platform=web", cookie)
        if not r or r.get("code") != 0:
            msg = (r or {}).get("message") or "无响应"
            raise AcquireError(ErrorCode.INTERNAL, f"读取收藏夹失败: {msg}")
        folders = [
            {
                "id": str(f.get("id")),
                "title": f.get("title") or "未命名收藏夹",
                "count": int(f.get("media_count") or 0),
            }
            for f in ((r.get("data") or {}).get("list") or [])
            if f.get("id") is not None
        ]
        return {"mid": mid, "uname": info.get("uname"), "folders": folders}

    async def fetch_fav_items(self, media_id: str, *, pn: int = 1, ps: int = 20) -> dict:
        """分页读取某个收藏夹内的视频，返回 bvid 供批量导入复用。

        失效（已删除/私有）的视频可能没有 bvid，直接跳过。
        """
        cookie = self._cookie_header()
        if not cookie:
            raise AcquireError(ErrorCode.NEED_LOGIN, "未配置 Cookie，无法读取收藏夹")
        url = (f"{FAV_RESOURCE_URL}?media_id={media_id}&pn={pn}&ps={ps}"
               f"&order=mtime&type=0&platform=web")
        r = await self._api_get(url, cookie)
        if not r or r.get("code") != 0:
            msg = (r or {}).get("message") or "无响应"
            raise AcquireError(ErrorCode.INTERNAL, f"读取收藏夹内容失败: {msg}")
        d = r.get("data") or {}
        items = []
        for m in (d.get("medias") or []):
            if not isinstance(m, dict) or not m.get("bvid"):
                continue
            items.append({
                "bvid": m["bvid"],
                "title": m.get("title") or "",
                "author": (m.get("upper") or {}).get("name") or "",
                "duration_s": int(m.get("duration") or 0),
                "cover": m.get("cover") or "",
            })
        info = d.get("info") or {}
        return {
            "media_id": str(media_id),
            "title": info.get("title") or "",
            "count": int(info.get("media_count") or 0),
            "page": pn,
            "has_more": bool(d.get("has_more")),
            "items": items,
        }

    # ---------- 错误分类（S2-09） ----------
    def _classify(self, err: str, out: str) -> AcquireError:
        e = (err or "") + (out or "")
        low = e.lower()
        if "requested format is not available" in low and "premium" in low:
            return AcquireError(ErrorCode.NOT_AUTHORIZED, "该清晰度需要会员（可尝试登录态或降低清晰度）")
        if "1080p" in low and "premium" in low:
            return AcquireError(ErrorCode.NOT_AUTHORIZED, "1080P 需会员")
        if "login" in low or "cookie" in low or "大会员" in e:
            return AcquireError(ErrorCode.NEED_LOGIN, "需要登录态")
        if "unsupported url" in low:
            return AcquireError(ErrorCode.UNSUPPORTED_URL, "不支持的 URL")
        if (err or "").strip().lower() == "timeout":
            # run_cmd 到点 kill() 的专用标记：并非网络故障，走可续传的超时分支
            return AcquireError(ErrorCode.TIMEOUT, "下载超时（已保留断点，可续传重试）",
                                retryable=True)
        if "timed out" in low or "timeout" in low or "connection" in low:
            return AcquireError(ErrorCode.NETWORK, "网络错误", retryable=True)
        if "unable to" in low and "extract" in low:
            return AcquireError(ErrorCode.FORMAT_CHANGED, "解析失败（平台结构可能变化）", retryable=True)
        return AcquireError(ErrorCode.INTERNAL, (err or "未知错误")[:300])
