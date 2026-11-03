"""S1 自测：配置 / 凭证 / 任务状态机 / 脱敏。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.core.config import MediaDirs, Settings, check_environment, load_settings
from apps.core.credentials import FileCredentialProvider, parse_cookie, redact
from apps.core.tasks import InvalidTransition, TaskManager, TaskState


# ---------- 配置 / 目录 ----------
def test_settings_defaults(tmp_path):
    s = Settings(data_root=tmp_path)
    assert s.data_root == tmp_path.resolve()
    assert s.asr_model == "small"
    assert s.subtitle_duration_tolerance_ms == 2000


def test_media_dirs_created(tmp_path):
    s = Settings(data_root=tmp_path)
    md = s.media
    md.ensure()
    for sub in ("original", "temp", "audio_work", "subtitles", "thumbnails"):
        assert (tmp_path / "media" / sub).is_dir()
    assert md.database.is_dir() and md.logs.is_dir()


def test_check_environment_runs(tmp_path):
    env = check_environment(Settings(data_root=tmp_path))
    assert "checks" in env and isinstance(env["checks"], list)
    names = {c["name"] for c in env["checks"]}
    assert "python>=3.12,<3.13" in names
    assert env["checks"][0]["ok"] is True


# ---------- Cookie 解析（S0 关键：URL 解码） ----------
def test_parse_cookie_url_encoded():
    raw = "0f6145a9%2C1795508593%2C7d471%2Aabc"
    c = parse_cookie(raw)
    assert c["SESSDATA"] == "0f6145a9,1795508593,7d471*abc"
    assert "%2C" not in c["SESSDATA"]


def test_parse_cookie_full_header():
    raw = "SESSDATA=abc%2C123; bili_jct=xyz; DedeUserID=42"
    c = parse_cookie(raw)
    assert c["SESSDATA"] == "abc,123"
    assert c["bili_jct"] == "xyz"
    assert c["DedeUserID"] == "42"


def test_parse_cookie_empty():
    assert parse_cookie("") == {}
    assert parse_cookie("   ") == {}


# ---------- 脱敏 ----------
def test_redact_cookie_values():
    msg = "Cookie: SESSDATA=secret123; bili_jct=abc"
    out = redact(msg)
    assert "secret123" not in out and "abc" not in out
    assert "SESSDATA=***" in out


# ---------- 凭证存储 ----------
def test_credential_roundtrip(tmp_path):
    p = FileCredentialProvider(tmp_path / "cred")
    p.set("bilibili", "SESSDATA=abc%2C123; bili_jct=xyz")
    got = p.get("bilibili")
    assert got["SESSDATA"] == "abc,123"
    assert p.status("bilibili") == "valid"
    p.clear("bilibili")
    assert p.status("bilibili") == "missing"
    assert p.get("bilibili") is None


def test_credential_backend_reported(tmp_path):
    p = FileCredentialProvider(tmp_path / "cred")
    assert p.backend in ("dpapi", "memory-only")


def test_credential_bad_input(tmp_path):
    p = FileCredentialProvider(tmp_path / "cred")
    from apps.core.credentials import CredentialError
    with pytest.raises(CredentialError):
        p.set("bilibili", "")


# ---------- 任务状态机 ----------
def test_task_happy_path():
    tm = TaskManager()
    t = tm.create(video_id="v1")
    assert t.state == TaskState.CREATED
    tm.transition(t.id, TaskState.MEDIA_PROCESSING, progress=10)
    tm.transition(t.id, TaskState.MEDIA_READY, progress=40)
    tm.transition(t.id, TaskState.TRANSCRIPT_PROCESSING, progress=50)
    tm.transition(t.id, TaskState.TRANSCRIPT_READY, progress=80)
    tm.transition(t.id, TaskState.AI_ANALYZING, progress=90)
    done = tm.transition(t.id, TaskState.COMPLETED, progress=100)
    assert done.state == TaskState.COMPLETED
    assert done.progress == 100


def test_task_invalid_transition():
    tm = TaskManager()
    t = tm.create()
    with pytest.raises(InvalidTransition):
        tm.transition(t.id, TaskState.COMPLETED)


def test_task_fail_and_retry():
    tm = TaskManager()
    t = tm.create()
    tm.transition(t.id, TaskState.MEDIA_PROCESSING)
    f = tm.transition(t.id, TaskState.FAILED, error_code="network", error_message="timeout")
    assert f.state == TaskState.FAILED and f.error_code == "network" and f.retry_count == 1
    r = tm.transition(t.id, TaskState.CREATED)
    assert r.state == TaskState.CREATED and r.error_code is None and r.progress == 0
