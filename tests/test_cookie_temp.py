"""Cookie 临时文件安全测试：不得落入当前工作目录，能可靠清理。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.adapters.bilibili import BilibiliAdapter


class FakeCred:
    def get(self, platform):
        return {"SESSDATA": "abc,123", "bili_jct": "xyz"}


def test_cookie_file_written_into_controlled_dir(tmp_path):
    ad = BilibiliAdapter(cookie_provider=FakeCred(), cookie_tmp_dir=tmp_path / "cookies")
    p = ad._new_cookie_file()
    assert ad._write_cookie_file(p) is True
    assert p.exists()
    assert p.parent == (tmp_path / "cookies")
    text = p.read_text(encoding="utf-8")
    assert text.startswith("# Netscape HTTP Cookie File")
    assert ".bilibili.com" in text and "SESSDATA" in text


def test_cookie_files_are_unique(tmp_path):
    ad = BilibiliAdapter(cookie_provider=FakeCred(), cookie_tmp_dir=tmp_path / "cookies")
    a, b = ad._new_cookie_file(), ad._new_cookie_file()
    assert a != b


def test_purge_stale_cookie_files(tmp_path):
    d = tmp_path / "cookies"
    d.mkdir()
    for i in range(3):
        (d / f"cookie_{i}.txt").write_text("x", encoding="utf-8")
    (d / "other.txt").write_text("keep", encoding="utf-8")
    n = BilibiliAdapter.purge_stale_cookie_files(d, older_than_sec=0)
    assert n == 3
    assert (d / "other.txt").exists()      # 非 cookie_* 不删


def test_purge_nonexistent_dir_is_safe(tmp_path):
    assert BilibiliAdapter.purge_stale_cookie_files(tmp_path / "nope", 0) == 0


def test_no_cookie_written_when_anonymous(tmp_path):
    ad = BilibiliAdapter(cookie_provider=None, cookie_tmp_dir=tmp_path / "cookies")
    assert ad._cookie_header() is None
    p = ad._new_cookie_file()
    assert ad._write_cookie_file(p) is False   # 无凭证不写文件


def test_default_cookie_dir_not_cwd():
    """默认目录应位于系统临时目录下的专用子目录，而不是当前工作目录。"""
    ad = BilibiliAdapter(cookie_provider=None)
    # 默认落在项目内 .tmp/cookies（沙箱下 TEMP 不可写，且绝不能落到项目根）
    assert ad._cookie_dir.name == "cookies"
    assert ".tmp" in str(ad._cookie_dir)
    assert ad._cookie_dir != Path.cwd()
