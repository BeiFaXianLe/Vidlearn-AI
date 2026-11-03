"""S3-04/05/06/07 自测：内嵌字幕提取、用户字幕导入、平台字幕标准化、Transcript 分段。

只测纯离线逻辑 + 本地样本（sample_with_sub.mkv 的 subrip 轨）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.core.subtitles import (
    cues_from_bilibili,
    extract_embedded_subtitles,
    normalize_cues,
    parse_ass,
    parse_srt,
    parse_vtt,
    to_srt,
)

TS = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "media"


# ---------- SRT ----------
def test_parse_srt_basic():
    srt = "1\n00:00:01,500 --> 00:00:03,000\nhello\n\n2\n00:00:04,000 --> 00:00:05,250\nworld\n"
    cues = parse_srt(srt)
    assert len(cues) == 2
    assert cues[0] == {"start_ms": 1500, "end_ms": 3000, "text": "hello"}
    assert cues[1] == {"start_ms": 4000, "end_ms": 5250, "text": "world"}


def test_parse_srt_bom_crlf_multiline_and_missing_index():
    # BOM + CRLF + 缺序号 + 多行文本
    srt = ("\ufeff00:00:01,000 --> 00:00:02,000\r\n"
           "line one\r\nline two\r\n\r\n"
           "2\r\n00:00:03,000 --> 00:00:04,000\r\nsingle\r\n")
    cues = parse_srt(srt)
    assert len(cues) == 2
    assert cues[0]["text"] == "line one\nline two"
    assert cues[0]["start_ms"] == 1000
    assert cues[1]["text"] == "single"


# ---------- VTT ----------
def test_parse_vtt_with_header_and_identifier():
    vtt = ("WEBVTT\n\n"
           "cue-1\n"
           "00:00:01.500 --> 00:00:03.000 align:start\n"
           "hello vtt\n\n"
           "00:00:04.000 --> 00:00:05.250\n"
           "multi\nline\n")
    cues = parse_vtt(vtt)
    assert len(cues) == 2
    assert cues[0] == {"start_ms": 1500, "end_ms": 3000, "text": "hello vtt"}
    assert cues[1]["text"] == "multi\nline"
    assert cues[1]["end_ms"] == 5250


def test_parse_vtt_note_block_skipped():
    vtt = "WEBVTT\n\nNOTE this is a comment\nspanning\n\n00:00:01.000 --> 00:00:02.000\nok\n"
    cues = parse_vtt(vtt)
    assert len(cues) == 1
    assert cues[0]["text"] == "ok"


# ---------- ASS ----------
def test_parse_ass_dialogue():
    ass = (
        "[Script Info]\nTitle: X\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.50,0:00:03.00,Default,,0,0,0,,hello, with comma\n"
        "Dialogue: 0,0:00:04.00,0:00:05.25,Default,,0,0,0,,{\\i1}styled text\n"
    )
    cues = parse_ass(ass)
    assert len(cues) == 2
    # 厘秒 → 毫秒
    assert cues[0]["start_ms"] == 1500
    assert cues[0]["end_ms"] == 3000
    assert cues[0]["text"] == "hello, with comma"
    assert cues[1]["text"] == "styled text"
    assert cues[1]["end_ms"] == 5250


def test_parse_ass_multiline_marker():
    ass = (
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,a\\Nb\n"
    )
    cues = parse_ass(ass)
    assert cues[0]["text"] == "a\nb"


# ---------- to_srt 往返 ----------
def test_to_srt_roundtrip():
    cues = [
        {"start_ms": 1500, "end_ms": 3000, "text": "hello"},
        {"start_ms": 60000, "end_ms": 61500, "text": "line one\nline two"},
    ]
    srt = to_srt(cues)
    back = parse_srt(srt)
    assert [{"start_ms": c["start_ms"], "end_ms": c["end_ms"], "text": c["text"]} for c in back] == cues


def test_to_srt_formatting():
    srt = to_srt([{"start_ms": 3723004, "end_ms": 3723999, "text": "x"}])
    assert "01:02:03,004 --> 01:02:03,999" in srt


# ---------- normalize_cues ----------
def test_normalize_sorts_and_drops_empty():
    cues = [
        {"start_ms": 3000, "end_ms": 4000, "text": "b"},
        {"start_ms": 1000, "end_ms": 2000, "text": "a"},
        {"start_ms": 5000, "end_ms": 6000, "text": "   "},
    ]
    out = normalize_cues(cues)
    assert [c["text"] for c in out] == ["a", "b"]
    assert out[0]["start_ms"] == 1000


def test_normalize_fixes_invalid_range():
    cues = [{"start_ms": 2000, "end_ms": 2000, "text": "x"},
            {"start_ms": 5000, "end_ms": 3000, "text": "y"}]
    out = normalize_cues(cues)
    for c in out:
        assert c["start_ms"] < c["end_ms"]
        assert isinstance(c["start_ms"], int) and isinstance(c["end_ms"], int)


def test_normalize_merges_adjacent_duplicates():
    cues = [
        {"start_ms": 1000, "end_ms": 2000, "text": "hi"},
        {"start_ms": 2000, "end_ms": 3000, "text": "hi"},
        {"start_ms": 3500, "end_ms": 4000, "text": "next"},
    ]
    out = normalize_cues(cues)
    assert len(out) == 2
    assert out[0] == {"start_ms": 1000, "end_ms": 3000, "text": "hi"}


# ---------- cues_from_bilibili ----------
def test_cues_from_bilibili():
    chosen = {
        "lang": "ai-zh",
        "source": "bilibili_ai",
        "cues": [
            {"start_ms": 2000, "end_ms": 3000, "text": "第二"},
            {"start_ms": 1000, "end_ms": 2000, "text": "第一"},
        ],
    }
    out = cues_from_bilibili(chosen)
    assert [c["text"] for c in out] == ["第一", "第二"]
    assert out[0]["start_ms"] == 1000


def test_cues_from_bilibili_empty():
    assert cues_from_bilibili(None) == []
    assert cues_from_bilibili({}) == []


# ---------- 内嵌字幕提取（真实样本） ----------
async def test_extract_embedded_subtitles(tmp_path):
    tracks = await extract_embedded_subtitles(TS / "sample_with_sub.mkv", tmp_path)
    assert len(tracks) == 1
    t = tracks[0]
    assert t["codec"] == "subrip"
    assert t["path"] and Path(t["path"]).exists()
    assert len(t["cues"]) > 0
    joined = " ".join(c["text"] for c in t["cues"]).lower()
    assert "first subtitle" in joined


async def test_extract_embedded_subtitles_none(tmp_path):
    tracks = await extract_embedded_subtitles(TS / "sample_no_sub.mp4", tmp_path)
    assert tracks == []

