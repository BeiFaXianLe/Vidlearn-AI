"""后台任务注册表（S3 导入 / S4 ASR 共用）。

前端通过 POST 拿到 task_id，再轮询 GET /api/tasks/{id} 查看阶段与进度。

任务持久化：传入 sqlite 连接后，任务写入 `jobs` 表，服务重启不会丢失；
重启时仍处于 running 的任务会被标记为「已中断」，前端可一键重试。
"""
from __future__ import annotations

import json
import threading
import uuid
from typing import Any


class JobStore:
    def __init__(self, conn=None, db_lock=None) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._conn = conn
        self._db_lock = db_lock or threading.RLock()
        if conn is not None:
            self._load()

    # ---------- 持久化 ----------
    def _persist(self, job: dict) -> None:
        if self._conn is None:
            return
        try:
            with self._db_lock:
                self._conn.execute(
                    "INSERT INTO jobs(id, data, created_at, updated_at) VALUES(?,?,?,?)"
                    " ON CONFLICT(id) DO UPDATE SET data=excluded.data,"
                    " updated_at=excluded.updated_at",
                    (job["id"], json.dumps(job, ensure_ascii=False),
                     job.get("created_at") or _now(), job.get("updated_at") or _now()))
                self._conn.commit()
        except Exception:      # 持久化失败不影响内存中的任务
            pass

    def _load(self) -> None:
        try:
            rows = self._conn.execute("SELECT data FROM jobs ORDER BY created_at").fetchall()
        except Exception:
            return
        with self._lock:
            for r in rows:
                try:
                    raw = r[0] if not isinstance(r, dict) else r["data"]
                    job = json.loads(raw)
                except (ValueError, KeyError, IndexError):
                    continue
                if job.get("status") == "running":
                    job["status"] = "error"
                    job["stage"] = "已中断"
                    job["control"] = "running"
                    job["error"] = {"code": "interrupted",
                                    "message": "服务重启导致任务中断，可点击重试"}
                    job["updated_at"] = _now()
                self._jobs[job["id"]] = job
            for job in self._jobs.values():
                self._persist(job)

    # ---------- 公开接口 ----------
    def create(self, *, stage: str = "排队中", payload: dict | None = None) -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            job = {"id": job_id, "status": "running", "stage": stage,
                   "progress": 0, "result": None, "error": None,
                   "control": "running", "payload": payload or {},
                   "created_at": _now()}
            self._jobs[job_id] = job
            self._persist(job)
        return job_id

    def control(self, job_id: str, action: str) -> dict | None:
        """action: pause | resume | cancel"""
        with self._lock:
            j = self._jobs.get(job_id)
            if j is None:
                return None
            if action == "pause" and j["status"] == "running":
                j["control"] = "paused"
                j["stage"] = "已暂停"
            elif action == "resume" and j["control"] == "paused":
                j["control"] = "running"
                j["stage"] = "恢复中"
            elif action == "cancel":
                j["control"] = "cancelled"
            j["updated_at"] = _now()
            self._persist(j)
            return dict(j)

    def is_cancelled(self, job_id: str) -> bool:
        j = self._jobs.get(job_id)
        return bool(j and j.get("control") == "cancelled")

    def is_paused(self, job_id: str) -> bool:
        j = self._jobs.get(job_id)
        return bool(j and j.get("control") == "paused")

    def update(self, job_id: str, **fields) -> None:
        with self._lock:
            j = self._jobs.get(job_id)
            if j is None:
                return
            for k, v in fields.items():
                if v is not None:
                    j[k] = v
            j["updated_at"] = _now()
            self._persist(j)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            j = self._jobs.get(job_id)
            return dict(j) if j else None

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._jobs.values())[-limit:]

    def delete(self, job_id: str) -> bool:
        """删除单个任务（内存 + 持久化）。返回是否删除成功。"""
        with self._lock:
            existed = self._jobs.pop(job_id, None) is not None
            if self._conn is not None:
                try:
                    with self._db_lock:
                        self._conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
                        self._conn.commit()
                except Exception:
                    pass
            return existed

    def delete_many(self, job_ids: list[str]) -> int:
        """批量删除任务，返回删除数量。"""
        n = 0
        with self._lock:
            for jid in job_ids:
                if self._jobs.pop(jid, None) is not None:
                    n += 1
            if self._conn is not None:
                try:
                    with self._db_lock:
                        self._conn.executemany("DELETE FROM jobs WHERE id=?",
                                               [(jid,) for jid in job_ids])
                        self._conn.commit()
                except Exception:
                    pass
        return n

    def prune(self, keep: int = 100) -> None:
        with self._lock:
            if len(self._jobs) <= keep:
                return
            ids = list(self._jobs.keys())[:-keep]
            for i in ids:
                self._jobs.pop(i, None)
            if self._conn is not None:
                try:
                    with self._db_lock:
                        self._conn.executemany(
                            "DELETE FROM jobs WHERE id=?", [(i,) for i in ids])
                        self._conn.commit()
                except Exception:
                    pass


def _now() -> str:
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).isoformat()
