"""后台任务持久化测试：重启后不丢任务，running 标记为已中断可重试。"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.core.jobs import JobStore
from apps.storage import init_db


def _new_store(db):
    return JobStore(conn=db, db_lock=threading.RLock())


def test_jobs_survive_restart_and_mark_interrupted(tmp_path):
    db = init_db(tmp_path / "t.db")
    s1 = _new_store(db)
    jid = s1.create(stage="下载媒体", payload={"source": "https://x"})
    s1.update(jid, title="示例标题", progress=20)

    # 模拟服务重启：新建 JobStore 从同一库加载
    s2 = _new_store(db)
    j = s2.get(jid)
    assert j is not None
    assert j["title"] == "示例标题"
    assert j["payload"]["source"] == "https://x"
    # 重启时仍 running → 标记为已中断、可重试
    assert j["status"] == "error"
    assert j["error"]["code"] == "interrupted"
    assert j["control"] == "running"


def test_paused_job_still_visible_after_restart(tmp_path):
    db = init_db(tmp_path / "t.db")
    s1 = _new_store(db)
    jid = s1.create(stage="下载媒体", payload={"source": "u"})
    s1.control(jid, "pause")
    assert s1.get(jid)["control"] == "paused"

    s2 = _new_store(db)
    j = s2.get(jid)
    assert j is not None                       # 不会消失
    assert j["status"] == "error"
    assert j["error"]["code"] == "interrupted"


def test_finished_job_keeps_terminal_state(tmp_path):
    db = init_db(tmp_path / "t.db")
    s1 = _new_store(db)
    jid = s1.create()
    s1.update(jid, status="done", progress=100, result={"video": {"title": "t"}})

    s2 = _new_store(db)
    j = s2.get(jid)
    assert j["status"] == "done"
    assert j["progress"] == 100
    assert j["result"]["video"]["title"] == "t"


def test_prune_removes_db_rows(tmp_path):
    db = init_db(tmp_path / "t.db")
    s = _new_store(db)
    ids = [s.create() for _ in range(5)]
    s.prune(keep=2)
    remaining = {r[0] for r in db.execute("SELECT id FROM jobs").fetchall()}
    assert remaining == set(ids[-2:])
