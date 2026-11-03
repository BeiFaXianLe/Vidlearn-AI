"""S6 媒体 Range 单测（解析与边界）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.api_s6_media import RANGE_RE


def test_range_regex_normal():
    m = RANGE_RE.match("bytes=100-200")
    assert m.group(1) == "100" and m.group(2) == "200"


def test_range_regex_open_end():
    m = RANGE_RE.match("bytes=100-")
    assert m.group(1) == "100" and m.group(2) == ""


def test_range_regex_suffix():
    m = RANGE_RE.match("bytes=-500")
    assert m.group(1) == "" and m.group(2) == "500"


def test_range_regex_invalid():
    assert RANGE_RE.match("bytes=abc") is None
    assert RANGE_RE.match("chars=0-1") is None
