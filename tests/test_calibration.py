"""字幕校准（术语/同音/QC/对齐/校准任务）测试。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

from apps.core import pinyin_util as py
from apps.core.align import snap_cues
from apps.core.calibrate import allowed_fix
from apps.core.subtitle_qc import score_cues


@pytest.fixture()
def client():
    import importlib
    import apps.main as main_mod
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c:
        yield c


def _mk_video_with_caption(client, title="镜舟科技发布会", cues=None, pid="cal1"):
    db = client.app.state.db
    from apps.storage import SourceCaptionRepo, VideoRepo
    with client.app.state.db_lock:
        v = VideoRepo(db).upsert(platform="bilibili", platform_video_id=pid, title=title, duration_ms=60000)
        cues = cues or [
            {"start_ms": 0, "end_ms": 3000, "text": "我是来自北京金州科技有限公司的石强"},
            {"start_ms": 3000, "end_ms": 6000, "text": "很开心分享荆州科技在全球化出海"},
        ]
        cap = SourceCaptionRepo(db).add(video_id=v["id"], source_type="asr_punct", language="zh",
                                        cues=cues, is_ai_generated=True, completeness_status="complete")
        from apps.storage import SegmentRepo
        SegmentRepo(db).replace_for_caption(video_id=v["id"], source_caption_id=cap["id"],
                                            source_type="asr_punct", language="zh", cues=cues)
    return v["id"], cap["id"]


# ---------------- 拼音同音/近音 ----------------
def test_fuzzy_pinyin_fixes_jinzhou_and_jingzhou():
    sig = py.term_signature("镜舟科技")
    out, hits = py.replace_homophones("北京金州科技有限公司", "镜舟科技", sig)
    assert out == "北京镜舟科技有限公司" and hits
    out2, _ = py.replace_homophones("分享荆州科技出海", "镜舟科技", sig)
    assert out2 == "分享镜舟科技出海"


def test_pinyin_does_not_touch_correct_or_english():
    sig = py.term_signature("镜舟科技")
    assert py.replace_homophones("镜舟科技很好", "镜舟科技", sig)[0] == "镜舟科技很好"
    # 英文不参与中文同音替换
    assert py.replace_homophones("StarRocks 数据", "镜舟科技", sig)[0] == "StarRocks 数据"


def test_term_signature_none_for_mixed():
    assert py.term_signature("AI赋能") is None   # 含英文，不做自动同音


# ---------------- QC ----------------
def test_qc_detects_variant_and_overlap():
    cues = [
        {"start_ms": 0, "end_ms": 2000, "text": "北京金州科技"},
        {"start_ms": 1500, "end_ms": 4000, "text": "北京金州科技"},   # 重叠 + 重复
    ]
    rep = score_cues(cues, duration_ms=10000, glossary_variants=["金州"])
    assert rep["score"] < 100
    assert rep["stats"]["variant_hits"] >= 1
    assert rep["stats"]["overlaps"] >= 1


def test_qc_perfect_score():
    cues = [{"start_ms": i * 2000, "end_ms": i * 2000 + 1900, "text": f"正常字幕第{i}段内容"} for i in range(5)]
    rep = score_cues(cues, duration_ms=10000)
    assert rep["score"] >= 90


# ---------------- LLM 修改校验 ----------------
def test_allowed_fix_rules():
    assert allowed_fix("北京金州科技", "北京镜舟科技", {"镜舟科技"}) is True
    assert allowed_fix("增长100%", "增长200%", set()) is False   # 改数字
    assert allowed_fix("我们做A和B", "我们做A", set()) is False   # 删内容
    assert allowed_fix("完全不同的另一段话", "毫不相干的内容", set()) is False


# ---------------- 回归：variants 来自 DB 的 JSON 字符串 ----------------
def test_variants_json_string_no_explosion():
    import asyncio
    from apps.core.calibrate import calibrate
    cues = [
        {"start_ms": 0, "end_ms": 3200, "text": "北京金州科技有限公司"},
        {"start_ms": 3200, "end_ms": 6000, "text": "分享荆州科技出海"},
    ]
    # 模拟从数据库读出的 variants 是 JSON 字符串（曾导致按字符替换、字幕爆炸）
    res = asyncio.run(calibrate(cues, terms=[{"term": "镜舟科技", "variants": '[\"金州科技\", \"荆州科技\"]'}],
                                llm=None, media_path=None, ffmpeg=None, duration_ms=60000,
                                do_pinyin=True, do_llm=False, do_align=False))
    assert len(res.changes) <= 2
    assert res.cues[0]["text"].count("镜舟科技") == 1
    assert len(res.cues[0]["text"]) < 30


def test_single_char_variants_ignored():
    import asyncio
    from apps.core.calibrate import calibrate
    cues = [{"start_ms": 0, "end_ms": 3000, "text": "今天金价上涨"}]
    res = asyncio.run(calibrate(cues, terms=[{"term": "镜舟科技", "variants": ["金"]}],
                                llm=None, media_path=None, ffmpeg=None, duration_ms=5000,
                                do_pinyin=True, do_llm=False, do_align=False))
    assert res.cues[0]["text"] == "今天金价上涨"   # 单字错误写法应被忽略


def test_longest_variant_first_no_double_suffix():
    import asyncio
    from apps.core.calibrate import calibrate
    cues = [{"start_ms": 0, "end_ms": 3000, "text": "北京金州科技有限公司"}]
    # 同时有「金州」和「金州科技」两个错误写法，应长词优先，不能变成「镜舟科技科技」
    res = asyncio.run(calibrate(cues, terms=[{"term": "镜舟科技", "variants": ["金州", "金州科技"]}],
                                llm=None, media_path=None, ffmpeg=None, duration_ms=5000,
                                do_pinyin=True, do_llm=False, do_align=False))
    assert res.cues[0]["text"] == "北京镜舟科技有限公司"


# ---------------- 时间轴对齐 ----------------
def test_snap_cues_to_silence():
    # 语音: [1000,3000) [4000,6000)，静音: [0,1000) [3000,4000) [6000,9999)
    sil = [(0, 1000), (3000, 4000), (6000, 9999)]
    cues = [{"start_ms": 500, "end_ms": 3500, "text": "a"},
            {"start_ms": 3800, "end_ms": 6500, "text": "b"}]
    out, ch = snap_cues(cues, sil, tolerance_ms=1000)
    assert out[0]["start_ms"] == 1000     # 起点从静音吸到语音开始
    assert out[0]["end_ms"] <= out[1]["start_ms"]  # 不重叠
    assert ch


# ---------------- API：术语表 ----------------
def test_glossary_crud_api(client):
    r = client.post("/api/glossary", json={"term": "镜舟科技", "variants": ["金州科技", "荆州科技"], "category": "品牌"})
    assert r.status_code == 200
    gid = r.json()["term"]["id"]
    assert any(t["term"] == "镜舟科技" for t in client.get("/api/glossary").json()["terms"])
    r2 = client.patch(f"/api/glossary/{gid}", json={"weight": 5})
    assert r2.json()["term"]["weight"] == 5
    assert client.delete(f"/api/glossary/{gid}").status_code == 200
    assert client.patch("/api/glossary/nope", json={"weight": 1}).status_code == 404


def test_glossary_extract_from_title(client):
    vid, _ = _mk_video_with_caption(client, title="镜舟科技 StarRocks 全球化发布会", pid="ext1")
    r = client.post("/api/glossary/extract", json={"video_id": vid, "save": True})
    body = r.json()
    assert body["ok"] and "candidates" in body
    assert any("镜舟科技" in c for c in body["candidates"])


# ---------------- API：QC + 校准 ----------------
def test_subtitle_qc_api(client):
    vid, cid = _mk_video_with_caption(client, pid="qc1")
    client.post("/api/glossary", json={"term": "镜舟科技", "variants": ["金州科技"], "scope": "video", "video_id": vid})
    r = client.get(f"/api/videos/{vid}/subtitle-qc")
    assert r.status_code == 200
    d = r.json()
    assert d["caption_id"] == cid and d["score"] is not None


def test_calibrate_endpoint_creates_corrected_track(client):
    vid, cid = _mk_video_with_caption(client, pid="cal2")
    client.post("/api/glossary", json={"term": "镜舟科技", "scope": "video", "video_id": vid})
    r = client.post(f"/api/videos/{vid}/calibrate", json={"do_llm": False, "do_align": False})
    assert r.status_code == 200
    tid = r.json()["task_id"]
    import time
    for _ in range(30):
        st = client.get(f"/api/tasks/{tid}").json()
        if st.get("status") in ("done", "error"):
            break
        time.sleep(0.2)
    assert st["status"] == "done", st
    assert st["result"]["changes"] >= 1
    # 变更日志里能看到 金州->镜舟
    ch = client.get(f"/api/videos/{vid}/caption-changes").json()["changes"]
    assert any("镜舟" in c["after"] for c in ch)
    # 新轨成为首选
    qc = client.get(f"/api/videos/{vid}/subtitle-qc").json()
    assert qc["source_type"] == "asr_corrected"


def test_delete_caption_reverts(client):
    vid, cid = _mk_video_with_caption(client, pid="rev1")
    client.post("/api/glossary", json={"term": "镜舟科技", "scope": "video", "video_id": vid})
    tid = client.post(f"/api/videos/{vid}/calibrate", json={"do_llm": False, "do_align": False}).json()["task_id"]
    import time
    for _ in range(30):
        st = client.get(f"/api/tasks/{tid}").json()
        if st.get("status") in ("done", "error"):
            break
        time.sleep(0.2)
    new_cid = st["result"]["caption_id"]
    assert client.delete(f"/api/videos/{vid}/captions/{new_cid}").status_code == 200
    # 回退后首选应回到原始轨（or 至少不是被删的轨）
    qc = client.get(f"/api/videos/{vid}/subtitle-qc").json()
    assert qc["caption_id"] != new_cid


def test_subtitle_replace_endpoint(client):
    vid, cid = _mk_video_with_caption(client, pid="rep1",
                                      cues=[{"start_ms": 0, "end_ms": 3000, "text": "北京金州科技有限公司"},
                                            {"start_ms": 3000, "end_ms": 6000, "text": "荆州科技出海"}])
    r = client.post(f"/api/videos/{vid}/subtitle-replace", json={"old": "金州", "new": "镜舟"})
    assert r.status_code == 200
    assert r.json()["replaced"] >= 1
    # 变更已写入
    ch = client.get(f"/api/videos/{vid}/caption-changes", params={"caption_id": cid}).json()["changes"]
    assert any("镜舟" in x["after"] for x in ch)
    # 空旧写法拒绝
    assert client.post(f"/api/videos/{vid}/subtitle-replace", json={"old": "  ", "new": "x"}).status_code == 400
