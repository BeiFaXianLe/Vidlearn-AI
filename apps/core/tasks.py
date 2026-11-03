"""任务状态机（S1-07）。

状态（PRD 冻结）：
CREATED → MEDIA_PROCESSING → MEDIA_READY
→ TRANSCRIPT_PROCESSING → TRANSCRIPT_READY
→ AI_ANALYZING → COMPLETED / FAILED
另有 CANCELLED。

本模块只负责状态流转的合法性与持久化抽象；具体存储由 repository 实现。
"""
from __future__ import annotations

import datetime as dt
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum


class TaskState(str, Enum):
    CREATED = "CREATED"
    MEDIA_PROCESSING = "MEDIA_PROCESSING"
    MEDIA_READY = "MEDIA_READY"
    TRANSCRIPT_PROCESSING = "TRANSCRIPT_PROCESSING"
    TRANSCRIPT_READY = "TRANSCRIPT_READY"
    AI_ANALYZING = "AI_ANALYZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# 允许的流转
ALLOWED: dict[TaskState, set[TaskState]] = {
    TaskState.CREATED: {TaskState.MEDIA_PROCESSING, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.MEDIA_PROCESSING: {TaskState.MEDIA_READY, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.MEDIA_READY: {TaskState.TRANSCRIPT_PROCESSING, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.TRANSCRIPT_PROCESSING: {TaskState.TRANSCRIPT_READY, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.TRANSCRIPT_READY: {TaskState.AI_ANALYZING, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.AI_ANALYZING: {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.COMPLETED: set(),
    TaskState.FAILED: {TaskState.CREATED},      # 重试
    TaskState.CANCELLED: set(),
}


class InvalidTransition(Exception):
    pass


@dataclass
class Task:
    id: str
    video_id: str | None = None
    stage: str = "import"
    state: TaskState = TaskState.CREATED
    progress: int = 0
    retry_count: int = 0
    error_code: str | None = None
    error_message: str | None = None
    created_at: str = field(default_factory=lambda: _now())
    updated_at: str = field(default_factory=lambda: _now())

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["state"] = self.state.value
        return d


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


class TaskManager:
    """内存实现（S1）；S2+ 可替换为 SQLite 持久化，接口不变。"""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()

    def create(self, video_id: str | None = None, stage: str = "import") -> Task:
        t = Task(id=uuid.uuid4().hex, video_id=video_id, stage=stage)
        with self._lock:
            self._tasks[t.id] = t
        return t

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list(self) -> list[Task]:
        return list(self._tasks.values())

    def transition(self, task_id: str, to: TaskState, *, progress: int | None = None,
                   error_code: str | None = None, error_message: str | None = None) -> Task:
        with self._lock:
            t = self._tasks.get(task_id)
            if t is None:
                raise KeyError(f"task {task_id} not found")
            if to not in ALLOWED[t.state]:
                raise InvalidTransition(f"{t.state.value} -> {to.value} 不允许")
            t.state = to
            t.updated_at = _now()
            if progress is not None:
                t.progress = progress
            if to == TaskState.FAILED:
                t.error_code = error_code
                t.error_message = error_message
                t.retry_count += 1
            if to == TaskState.CREATED:
                t.progress = 0
                t.error_code = None
                t.error_message = None
            return t
