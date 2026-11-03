"""S5 测试：AI 编排（用假 LLM）+ 持久化 + 时间戳防伪。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.core import ai
from apps.core.analysis import AnalysisService, transcript_hash
from apps.storage import SegmentRepo, SourceCaptionRepo, VideoRepo, init_db
from apps.storage.analysis_repos import ChapterRepo, KnowledgePointRepo, SummaryRepo


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload

    async def complete_json(self, system, user, schema):
        return dict(self.payload)


def _db(tmp_path):
    conn = init_db(tmp_path / "t.db")
    vrepo, crepo, srepo = VideoRepo(conn), SourceCaptionRepo(conn), SegmentRepo(conn)
    v = vrepo.upsert(platform="bilibili", platform_video_id="BV1", title="测试视频", duration_ms=60000)
    cap = crepo.add(video_id=v["id"], source_type="bilibili_ai", language="zh",
                    cues=[{"start_ms": 0, "end_ms": 3000, "text": "开场"},
                          {"start_ms": 3000, "end_ms": 8000, "text": "第一部分"},
                          {"start_ms": 8000, "end_ms": 20000, "text": "第二部分"}],
                    is_ai_generated=True, completeness_status="complete")
    srepo.replace_for_caption(video_id=v["id"], source_caption_id=cap["id"],
                              source_type="bilibili_ai", language="zh",
                              cues=[{"start_ms": 0, "end_ms": 3000, "text": "开场"},
                                    {"start_ms": 3000, "end_ms": 8000, "text": "第一部分"},
                                    {"start_ms": 8000, "end_ms": 20000, "text": "第二部分"}])
    svc = AnalysisService(vrepo, srepo, SummaryRepo(conn), ChapterRepo(conn),
                          KnowledgePointRepo(conn), None)
    return conn, v, svc


@pytest.mark.asyncio
async def test_summary_persist_and_scope_authoritative(tmp_path):
    conn, v, svc = _db(tmp_path)
    svc.llm = FakeLLM({"one_liner": "一句话", "key_points": ["a", "b"],
                       "terms": ["x"], "audience": "开发", "content_scope": "full"})
    s = await svc.summarize(v["id"], mode="quick", content_scope="partial")
    assert s["content"]["one_liner"] == "一句话"
    # 系统判定优先，不信模型返回的 full
    assert s["content_scope"] == "partial"
    assert s["transcript_hash"]
    conn.close()


@pytest.mark.asyncio
async def test_chapters_timestamps_snapped(tmp_path):
    conn, v, svc = _db(tmp_path)
    # 模型给了一个不存在但接近 8000 的时间戳 8200，应 snap 到 8000；给 999999 应清空
    svc.llm = FakeLLM({"chapters": [
        {"title": "开场", "start_ms": 0, "end_ms": 3000, "summary": "s1"},
        {"title": "第一部分", "start_ms": 3200, "end_ms": 8000, "summary": "s2"},
        {"title": "伪造", "start_ms": 999999, "end_ms": 1000000, "summary": "bad"},
    ]})
    chs = await svc.build_chapters(v["id"])
    assert len(chs) >= 2
    starts = [c["start_ms"] for c in chs]
    assert 3200 not in starts  # 被 snap 到 3000
    # 伪造的时间戳被清 None 或整条保留但 start_ms=None
    bad = [c for c in chs if c["title"] == "伪造"]
    if bad:
        assert bad[0]["start_ms"] is None
    conn.close()


@pytest.mark.asyncio
async def test_points_persist(tmp_path):
    conn, v, svc = _db(tmp_path)
    svc.llm = FakeLLM({"knowledge_points": [
        {"title": "概念A", "content": "解释", "start_ms": 3000},
        {"title": "概念B", "content": "解释2"},
    ]})
    pts = await svc.build_points(v["id"])
    assert len(pts) == 2
    assert pts[0]["title"] == "概念A"
    conn.close()


@pytest.mark.asyncio
async def test_no_subtitle_raises(tmp_path):
    conn = init_db(tmp_path / "t2.db")
    vrepo = VideoRepo(conn)
    v = vrepo.upsert(platform="local", platform_video_id="x", title="无字幕")
    svc = AnalysisService(vrepo, SegmentRepo(conn), SummaryRepo(conn), ChapterRepo(conn),
                          KnowledgePointRepo(conn), FakeLLM({}))
    with pytest.raises(ValueError):
        await svc.summarize(v["id"])
    conn.close()


def test_normalize_timestamps_far_value_nulled():
    cues = [{"start_ms": 0, "end_ms": 1000, "text": "a"},
            {"start_ms": 5000, "end_ms": 6000, "text": "b"}]
    items = [{"start_ms": 5100}, {"start_ms": 999999}, {"start_ms": None}]
    out = ai.normalize_timestamps(items, None, cues)
    assert out[0]["start_ms"] == 5000
    assert out[1]["start_ms"] is None
    assert out[2]["start_ms"] is None


def test_build_transcript_context_truncates():
    cues = [{"start_ms": i * 1000, "end_ms": i * 1000 + 500, "text": "x" * 100} for i in range(1000)]
    ctx = ai.build_transcript_context(cues, max_chars=500)
    assert "已截断" in ctx
    assert len(ctx) < 2000


def test_schema_validation_rejects_missing_field():
    with pytest.raises(ai.LLMError):
        ai._validate_schema({"one_liner": "x"}, ai.SUMMARY_SCHEMA)


def test_transcript_hash_stable():
    cues = [{"start_ms": 0, "end_ms": 1, "text": "a"}]
    assert transcript_hash(cues) == transcript_hash(cues)
