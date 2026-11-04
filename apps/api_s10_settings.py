"""S10 API：应用设置（个人职业档案、AI 偏好）。

职业档案用于 AI 总结环节生成「职业发展建议」——告诉模型「这个人是谁」，
建议才有针对性。
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from apps.core.logging_setup import get_logger
from apps.storage.repositories import SettingsRepo

router = APIRouter(prefix="/api", tags=["s10"])
log = get_logger("settings-api")

# app_settings 里的键名
KEY_PROFILE = "user_profile"

# 职业标签（前端一键选择，也可自由输入）
CAREER_TAGS = [
    "产品经理", "程序员", "设计师", "运营", "市场", "销售",
    "教师", "学生", "医生", "律师", "财务", "投资人",
    "创业者", "自由职业", "管理者", "研究者",
]


def _repo(request: Request) -> SettingsRepo:
    return SettingsRepo(request.app.state.db)


class ProfileIn(BaseModel):
    career: str = ""       # 职业名称（可自由输入）
    tags: list[str] = []   # 选中的职业标签
    goal: str = ""         # 想达成的目标（可选，一句话）
    industry: str = ""     # 所在行业（可选）


def _load(request: Request) -> dict:
    import json
    raw = _repo(request).get(KEY_PROFILE)
    if not raw:
        return {"career": "", "tags": [], "goal": "", "industry": ""}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {"career": "", "tags": [], "goal": "", "industry": ""}
    return {
        "career": data.get("career") or "",
        "tags": data.get("tags") or [],
        "goal": data.get("goal") or "",
        "industry": data.get("industry") or "",
    }


@router.get("/settings/profile")
def get_profile(request: Request):
    """读取个人职业档案。"""
    return {"ok": True, "profile": _load(request), "career_tags": CAREER_TAGS}


@router.put("/settings/profile")
def put_profile(body: ProfileIn, request: Request):
    """保存个人职业档案（写 app_settings，本机 SQLite）。"""
    import json

    tags = [t.strip() for t in (body.tags or []) if t and t.strip()][:12]
    payload = {
        "career": (body.career or "").strip()[:60],
        "tags": tags,
        "goal": (body.goal or "").strip()[:200],
        "industry": (body.industry or "").strip()[:40],
    }
    _repo(request).set(KEY_PROFILE, json.dumps(payload, ensure_ascii=False))
    log.info("已保存职业档案: career=%s tags=%d", payload["career"] or "-", len(tags))
    return {"ok": True, "profile": payload}
