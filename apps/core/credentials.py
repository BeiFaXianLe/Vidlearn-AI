"""凭证管理（S1-03/04/05/06）。

设计要点（来自 S0 实测与 V2.0 D01/D02）：
- 存储：Windows DPAPI（CryptProtectData），密文落盘；明文仅内存。
- 导入：用户粘贴的 Cookie 可能经 URL 编码，必须 unquote（S0 实测：编码形式被 B站判 -101）。
- 日志：不得输出 cookie 值，提供 redact() 统一脱敏。
- 非 Windows 平台：DPAPI 不可用时降级为「内存态 + 明确告警」，绝不退化为明文落盘。
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

SENSITIVE_KEYS = ("SESSDATA", "ttwid", "s_v_web_id", "msToken", "bili_jct", "DedeUserID__ckMd5")


class CredentialError(Exception):
    pass


class CredentialProvider(Protocol):
    def get(self, platform: str) -> dict[str, str] | None: ...
    def set(self, platform: str, raw: str) -> None: ...
    def clear(self, platform: str) -> None: ...
    def status(self, platform: str) -> str: ...  # valid | expired | missing


# ---------------- DPAPI 后端 ----------------

class _Dpapi:
    """Windows DPAPI 封装。"""

    def __init__(self) -> None:
        try:
            import ctypes
            from ctypes import wintypes

            self._ctypes = ctypes
            class DATA_BLOB(ctypes.Structure):
                _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

            self._DATA_BLOB = DATA_BLOB
            self._crypt32 = ctypes.windll.crypt32
            self._kernel32 = ctypes.windll.kernel32
            self.available = True
        except Exception:
            self.available = False

    def _blob(self, data: bytes):
        ctypes = self._ctypes
        buf = ctypes.create_string_buffer(data, len(data))
        return self._DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    def _from_blob(self, blob) -> bytes:
        ctypes = self._ctypes
        n = blob.cbData
        buf = ctypes.string_at(blob.pbData, n)
        self._kernel32.LocalFree(blob.pbData)
        return buf

    def protect(self, data: bytes, entropy: bytes = b"vidlearn") -> bytes:
        ctypes = self._ctypes
        ent = self._blob(entropy)
        src = self._blob(data)
        out = self._DATA_BLOB()
        ok = self._crypt32.CryptProtectData(
            ctypes.byref(src), None, ctypes.byref(ent), None, None, 0, ctypes.byref(out))
        if not ok:
            raise CredentialError("DPAPI CryptProtectData 失败")
        return self._from_blob(out)

    def unprotect(self, data: bytes, entropy: bytes = b"vidlearn") -> bytes:
        ctypes = self._ctypes
        ent = self._blob(entropy)
        src = self._blob(data)
        out = self._DATA_BLOB()
        ok = self._crypt32.CryptUnprotectData(
            ctypes.byref(src), None, ctypes.byref(ent), None, None, 0, ctypes.byref(out))
        if not ok:
            raise CredentialError("DPAPI CryptUnprotectData 失败（可能跨用户/跨机器）")
        return self._from_blob(out)


# ---------------- 文件后端 ----------------

class _Fernet:
    """POSIX 平台加密后端：cryptography.Fernet（AES128-CBC + HMAC）。

    密钥文件放在凭证目录下（0600），只允许当前用户读取。
    未安装 cryptography 时 available=False，调用方退化为内存态。
    """

    def __init__(self, key_dir: Path) -> None:
        try:
            from cryptography.fernet import Fernet  # type: ignore
        except Exception:
            self.available = False
            self._f = None
            return
        self.available = True
        self._fernet_cls = Fernet
        key_dir = Path(key_dir)
        try:
            key_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.available = False
            self._f = None
            return
        key_path = key_dir / ".secret.key"
        try:
            if key_path.exists():
                key = key_path.read_bytes().strip()
            else:
                key = Fernet.generate_key()
                key_path.write_bytes(key)
                _restrict_permissions(key_path)
        except OSError:
            self.available = False
            self._f = None
            return
        try:
            self._f = Fernet(key)
        except Exception:
            self.available = False
            self._f = None

    def protect(self, data: bytes, entropy: bytes = b"") -> bytes:
        return self._f.encrypt(data)

    def unprotect(self, data: bytes, entropy: bytes = b"") -> bytes:
        return self._f.decrypt(data)


class FileCredentialProvider:
    """凭证提供者。

    - Windows：DPAPI（用户绑定，绑定当前 Windows 账户）
    - Linux/macOS：Fernet（密钥文件 0600，仅当前用户可读）
    - 两者都不可用：仅内存（重启丢失，并给出告警）
    """

    def __init__(self, store_dir: Path) -> None:
        self._dir = Path(store_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._dpapi = _Dpapi()
        if self._dpapi.available:
            self._cipher = self._dpapi
            self._backend = "dpapi"
        else:
            fernet = _Fernet(self._dir)
            if fernet.available:
                self._cipher = fernet
                self._backend = "fernet"
            else:
                self._cipher = None
                self._backend = "memory-only"
        self._memory: dict[str, dict[str, str]] = {}

    def _path(self, platform: str) -> Path:
        return self._dir / f"{_safe_name(platform)}.cred"

    # -- 公开接口 --
    def set(self, platform: str, raw: str) -> None:
        cookies = parse_cookie(raw)
        if not cookies:
            raise CredentialError("无法解析 Cookie：请粘贴 'k=v; k2=v2' 或 SESSDATA 值")
        self._memory[platform] = cookies
        if self._cipher is not None:
            payload = json.dumps(cookies, ensure_ascii=False).encode("utf-8")
            enc = self._cipher.protect(payload)
            p = self._path(platform)
            p.write_bytes(base64.b64encode(enc))
            _restrict_permissions(p)

    def get(self, platform: str) -> dict[str, str] | None:
        if platform in self._memory:
            return dict(self._memory[platform])
        p = self._path(platform)
        if not p.exists():
            return None
        if self._cipher is None:
            return None
        try:
            enc = base64.b64decode(p.read_bytes())
            return dict(json.loads(self._cipher.unprotect(enc).decode("utf-8")))
        except Exception:
            return None

    def clear(self, platform: str) -> None:
        self._memory.pop(platform, None)
        p = self._path(platform)
        if p.exists():
            p.unlink()

    def status(self, platform: str) -> str:
        if self._cipher is not None:
            return "valid" if self._path(platform).exists() else "missing"
        return "valid" if platform in self._memory else "missing"

    @property
    def backend(self) -> str:
        return self._backend


# ---------------- 工具函数 ----------------

def parse_cookie(raw: str) -> dict[str, str]:
    """解析并标准化 Cookie。

    S0 实测：SESSDATA 可能以 URL 编码形式提供，必须先 unquote。
    """
    raw = (raw or "").strip().strip("\"'")
    if not raw:
        return {}
    # 若整体没有 '=' 且形似 SESSDATA（含 %2C），视为纯 SESSDATA 值
    if "=" not in raw:
        return {"SESSDATA": urllib.parse.unquote(raw)}

    out: dict[str, str] = {}
    for part in re.split(r"[;\n]", raw):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        if not k:           # 拒绝空键（如 ";;;==="）
            continue
        out[k] = urllib.parse.unquote(v.strip())
    return out


def redact(text: str) -> str:
    """统一脱敏：把敏感 cookie 值替换为 ***。"""
    if not text:
        return text
    for key in SENSITIVE_KEYS:
        text = re.sub(rf"({key}\s*[=:]\s*)([^;\s,}}]+)", r"\1***", text)
    return text


def _safe_name(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]", "_", s)


def _restrict_permissions(path: Path) -> None:
    """仅当前用户可读（fail-open）。Windows 用 icacls，POSIX 用 chmod 600。"""
    if sys.platform != "win32":
        try:
            import os as _os
            _os.chmod(path, 0o600)
        except OSError:
            pass
        return
    try:
        import subprocess

        # 用 whoami 拿真实限定名（DOMAIN\\user），避免 USERNAME 大小写/域不一致
        who = subprocess.run(["whoami"], capture_output=True, text=True, check=False)
        user = (who.stdout or "").strip()
        if not user:
            return
        r = subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
            capture_output=True, text=True, check=False,
        )
        if r.returncode != 0:
            # fail-open：恢复继承，避免文件不可读
            subprocess.run(["icacls", str(path), "/inheritance:e"],
                           capture_output=True, check=False)
    except Exception:
        pass


@dataclass
class CredentialInfo:
    platform: str
    backend: str
    status: str
    keys: list[str]

