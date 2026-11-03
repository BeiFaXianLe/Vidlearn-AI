"""S3-01 数据库与入库编排测试。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.adapters.base import MediaResult, VideoMeta
from apps.core.intake import CaptionIntake, MediaIntake, SOURCE_PRIORITY
from apps.storage import (
    MediaAssetRepo,
    SegmentRepo,
    SourceCaptionRepo,
    VideoRepo,
    init_db,
)


@pytest.fixture()
def repos(tmp_path):
    db = init_db(tmp_path / "t.db")
    yield VideoRepo(db), MediaAssetRepo(db), SourceCaptionRepo(db), SegmentRepo(db)
    db.close()


def _meta(**kw):
    base = dict(platform="bilibili", platform_video_id="BV1x", title="t", duration_ms=10000)
    base.update(kw)
    return VideoMeta(**base)


def test_register_and_attach(repos, tmp_path):
    vrepo, arepo, crepo, srepo = repos
    v = MediaIntake(vrepo, arepo).register_video(_meta())
    f = tmp_path / "a.mp4"
    f.write_bytes(b"x" * 100)
    res = MediaResult(file_path=f, container="mp4", sha256="a" * 64,
                      declared_duration_ms=10000, width=640, height=360,
                      vcodec="h264", acodec="aac", has_audio=True)
    asset = MediaIntake(vrepo, arepo).attach_media(v["id"], res,
                                                   integrity_verdict="verified",
                                                   acquired_from="bilibili")
    assert asset["status"] == "verified"
    assert vrepo.get(v["id"])["media_status"] == "downloaded"


def test_attach_invalid_marks_failed(repos, tmp_path):
    vrepo, arepo, _, _ = repos
    v = MediaIntake(vrepo, arepo).register_video(_meta())
    f = tmp_path / "b.mp4"; f.write_bytes(b"y")
    res = MediaResult(file_path=f, container="mp4", sha256="b" * 64, declared_duration_ms=0)
    MediaIntake(vrepo, arepo).attach_media(v["id"], res,
                                           integrity_verdict="invalid", acquired_from="local")
    assert vrepo.get(v["id"])["media_status"] == "failed"


def test_multi_caption_tracks_and_primary(repos):
    vrepo, arepo, crepo, srepo = repos
    v = MediaIntake(vrepo, arepo).register_video(_meta())
    ci = CaptionIntake(vrepo, crepo, srepo)
    cues = [{"start_ms": 0, "end_ms": 900, "text": "hi"}]
    ci.add_track(video_id=v["id"], source_type="asr", language="zh", cues=cues,
                 completeness="partial")
    ci.add_track(video_id=v["id"], source_type="bilibili_human", language="zh", cues=cues,
                 completeness="complete")
    tracks = crepo.for_video(v["id"])
    assert len(tracks) == 2  # 多轨并存，不覆盖
    primary = ci.choose_primary(v["id"])
    assert primary["source_type"] == "bilibili_human"  # 人工字幕优先于 asr


def test_segments_persist(repos):
    vrepo, arepo, crepo, srepo = repos
    v = MediaIntake(vrepo, arepo).register_video(_meta())
    ci = CaptionIntake(vrepo, crepo, srepo)
    cues = [{"start_ms": 0, "end_ms": 500, "text": "a"},
            {"start_ms": 500, "end_ms": 1000, "text": "b"},
            {"start_ms": 1000, "end_ms": 1500, "text": "c"}]
    cap = ci.add_track(video_id=v["id"], source_type="bilibili_ai", language="zh",
                       cues=cues, completeness="complete")
    assert cap["segment_count"] == 3
    segs = srepo.for_video(v["id"], cap["id"])
    assert [s["text"] for s in segs] == ["a", "b", "c"]
    assert vrepo.get(v["id"])["transcript_status"] == "complete"


def test_upsert_is_idempotent(repos):
    vrepo, arepo, _, _ = repos
    mi = MediaIntake(vrepo, arepo)
    v1 = mi.register_video(_meta(title="A"))
    v2 = mi.register_video(_meta(title="B"))
    assert v1["id"] == v2["id"]
    assert v2["title"] == "B"


def test_source_priority_order():
    assert SOURCE_PRIORITY["bilibili_human"] < SOURCE_PRIORITY["bilibili_ai"] < SOURCE_PRIORITY["asr"]
