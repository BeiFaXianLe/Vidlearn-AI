"""抖音 CDP 通道测试（不依赖真实浏览器/网络）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.core import douyin_cdp


def test_filter_only_douyin_domains():
    cookies = [
        {"name": "ttwid", "value": "v1", "domain": ".douyin.com"},
        {"name": "s_v_web_id", "value": "v2", "domain": "www.douyin.com"},
        {"name": "sid", "value": "x", "domain": ".ttwid.cn"},
        {"name": "session", "value": "y", "domain": "www.workbuddy.cn"},   # 其它站点，必须排除
        {"name": "", "value": "z", "domain": "www.douyin.com"},            # 空名，必须排除
    ]
    out = douyin_cdp._filter(cookies)
    assert set(out) == {"ttwid", "s_v_web_id", "sid"}
    assert out["ttwid"] == "v1"


def test_cookie_header_format():
    assert douyin_cdp.cookie_header({"a": "1", "b": "2"}) == "a=1; b=2"
    assert douyin_cdp.cookie_header({}) == ""


def test_to_netscape_session_cookie_and_empty_name():
    text = douyin_cdp.to_netscape([
        {"name": "ttwid", "value": "v", "domain": ".douyin.com", "path": "/",
         "expires": -1, "secure": True},
        {"name": "", "value": "x", "domain": ".douyin.com", "path": "/"},
        {"name": "msToken", "value": "m", "domain": "www.douyin.com", "path": "/",
         "expires": 1893456000, "secure": False},
    ])
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    assert len(lines) == 2
    assert lines[0].split("\t")[4] == "0"          # 会话 cookie -> 0（-1 会被 yt-dlp 判非法）
    assert lines[0].split("\t")[5] == "ttwid"
    assert lines[1].split("\t")[4] == "1893456000"


def test_cdp_available_false_when_no_browser():
    # 端口 1 几乎不可能有浏览器在听
    assert douyin_cdp.cdp_available(1, timeout=0.3) is False


def test_default_port_not_9222():
    # 9222 常被其它工具占用（实测本机 WorkBuddy 内置 Chromium 就占着）
    assert douyin_cdp.DEFAULT_PORT != 9222


@pytest.fixture()
def client():
    import importlib
    import apps.main as main_mod
    importlib.reload(main_mod)
    from fastapi.testclient import TestClient
    with TestClient(main_mod.app) as cl:
        yield cl


def test_cdp_endpoint_without_browser(client):
    r = client.post("/api/credentials/douyin/cdp", json={"port": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "调试端口" in body["message"]


def test_login_endpoint_launches_browser(client, monkeypatch):
    calls = {}

    def fake_launch(profile_dir, port=None, url=None):
        calls["profile_dir"] = profile_dir
        calls["port"] = port
        return 4321

    monkeypatch.setattr("apps.core.douyin_cdp.launch_login_browser", fake_launch)
    r = client.post("/api/credentials/douyin/login", json={"port": 9333})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["pid"] == 4321
    assert calls["port"] == 9333
    assert "douyin" in calls["profile_dir"]


def test_cdp_endpoint_saves_cookie(client, monkeypatch):
    async def fake_export(port=None):
        return {"ttwid": "abc", "s_v_web_id": "def"}

    client.delete("/api/credentials/douyin")          # 清掉历史残留，保证从"未配置"开始
    monkeypatch.setattr("apps.core.douyin_cdp.export_cookies", fake_export)
    r = client.post("/api/credentials/douyin/cdp", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["count"] == 2
    assert body["status"] == "valid"
    # 已落库（DPAPI/内存），可再读出
    st = client.get("/api/credentials/douyin").json()
    assert st["status"] == "valid"
    assert set(st["keys"]) == {"ttwid", "s_v_web_id"}
    client.delete("/api/credentials/douyin")          # 不污染其它用例


def test_verify_endpoint_douyin_uses_correct_kwargs(client):
    """回归：verify 之前给 DouyinAdapter 传了错的参数名（douyin_use_browser），必然 TypeError。"""
    client.delete("/api/credentials/douyin")
    r = client.post("/api/credentials/verify", json={"platform": "douyin"})
    assert r.status_code == 200
    body = r.json()
    # 未配置 cookie -> ok=False，且不是参数错误
    assert body["ok"] is False
    assert "unexpected keyword" not in (body.get("message") or "")
