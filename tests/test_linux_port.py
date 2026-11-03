"""Linux 移植相关测试：Fernet 加密后端 + 权限 + 跨平台回退。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.core import credentials as cred_mod
from apps.core.credentials import FileCredentialProvider, _Fernet

crypto = pytest.importorskip("cryptography", reason="需要 cryptography 才能测试 Fernet 后端")


# ---------- Fernet 后端 ----------
def test_fernet_roundtrip(tmp_path):
    f = _Fernet(tmp_path)
    assert f.available is True
    data = b'{"SESSDATA": "abc,123"}'
    enc = f.protect(data)
    assert enc != data
    assert f.unprotect(enc) == data


def test_fernet_key_file_created_with_restrictive_mode(tmp_path):
    _Fernet(tmp_path)
    key = tmp_path / ".secret.key"
    assert key.exists()
    if os.name == "posix":
        mode = key.stat().st_mode & 0o777
        assert mode == 0o600


def test_fernet_reload_same_key(tmp_path):
    f1 = _Fernet(tmp_path)
    token = f1.protect(b"hello")
    f2 = _Fernet(tmp_path)          # 重新加载同一密钥
    assert f2.unprotect(token) == b"hello"


def test_fernet_different_dirs_incompatible(tmp_path):
    a = _Fernet(tmp_path / "a")
    b = _Fernet(tmp_path / "b")
    token = a.protect(b"x")
    with pytest.raises(Exception):
        b.unprotect(token)


# ---------- 后端选择 ----------
def test_backend_selection_is_platform_appropriate(tmp_path):
    p = FileCredentialProvider(tmp_path)
    if sys.platform == "win32":
        assert p.backend in ("dpapi", "fernet", "memory-only")
    else:
        assert p.backend in ("fernet", "memory-only")


def test_non_windows_uses_fernet_and_persists(tmp_path, monkeypatch):
    """模拟非 Windows：应选 Fernet 并跨实例持久化（不依赖 DPAPI）。"""
    monkeypatch.setattr(cred_mod.sys, "platform", "linux")
    # 用一个 DPAPI 不可用的桩类替换（实例属性在 __init__ 内设置，需替换类本身）
    class _NoDpapi:
        available = False
    monkeypatch.setattr(cred_mod, "_Dpapi", _NoDpapi)

    p1 = FileCredentialProvider(tmp_path / "cred")
    assert p1.backend == "fernet"
    p1.set("bilibili", "SESSDATA=abc%2C123; bili_jct=xyz")

    # 新实例（模拟重启）仍能读回 —— 证明落盘加密可用
    p2 = FileCredentialProvider(tmp_path / "cred")
    got = p2.get("bilibili")
    assert got is not None and got["SESSDATA"] == "abc,123"
    assert p2.status("bilibili") == "valid"


def test_credential_file_not_plaintext(tmp_path, monkeypatch):
    monkeypatch.setattr(cred_mod.sys, "platform", "linux")
    class _NoDpapi2:
        available = False
    monkeypatch.setattr(cred_mod, "_Dpapi", _NoDpapi2)
    p = FileCredentialProvider(tmp_path / "cred")
    p.set("bilibili", "SESSDATA=supersecretvalue123")
    raw = (tmp_path / "cred" / "bilibili.cred").read_bytes()
    assert b"supersecretvalue123" not in raw       # 密文不含明文
