"""S10 设置（职业档案）与 AI 总结注入职业建议的测试。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest


@pytest.fixture()
def client():
    import importlib
    import apps.main as main_mod
    importlib.reload(main_mod)
    from fastapi.testclient import TestClient
    with TestClient(main_mod.app) as cl:
        yield cl


def test_profile_defaults_empty(client):
    client.put("/api/settings/profile", json={"career": "", "tags": [], "goal": "", "industry": ""})
    r = client.get("/api/settings/profile")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["profile"]["career"] == ""
    assert len(body["career_tags"]) > 0


def test_profile_roundtrip(client):
    payload = {"career": "后端工程师", "tags": ["程序员", "管理者"],
               "goal": "半年内带小团队", "industry": "互联网"}
    r = client.put("/api/settings/profile", json=payload)
    assert r.status_code == 200 and r.json()["ok"] is True
    got = client.get("/api/settings/profile").json()["profile"]
    assert got["career"] == "后端工程师"
    assert got["tags"] == ["程序员", "管理者"]
    assert got["goal"] == "半年内带小团队"


def test_profile_trims_and_limits(client):
    payload = {"career": "  " + "x" * 100 + "  ", "tags": [f"t{i}" for i in range(20)],
               "goal": "g" * 500, "industry": "i" * 100}
    r = client.put("/api/settings/profile", json=payload)
    got = r.json()["profile"]
    assert len(got["career"]) <= 60
    assert len(got["tags"]) <= 12
    assert len(got["goal"]) <= 200
    assert len(got["industry"]) <= 40


def test_summary_prompt_includes_career_only_when_profile():
    """有档案时用 CAREER 提示词并要求 career_advice；无档案用普通提示词。"""
    from apps.core import ai
    assert "职业发展" in ai.SYSTEM_SUMMARY_CAREER
    assert "career_advice" in ai.SUMMARY_SCHEMA["properties"]
    # 普通提示词不要求职业建议
    assert "career_advice" not in ai.SYSTEM_SUMMARY
