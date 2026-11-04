"""S5 分析编排：从字幕生成摘要/章节/知识点并入库。"""
from __future__ import annotations

import hashlib
import json

from apps.core import ai
from apps.core.logging_setup import get_logger
from apps.storage.analysis_repos import ChapterRepo, KnowledgePointRepo, SummaryRepo
from apps.storage.repositories import SegmentRepo, VideoRepo

log = get_logger("analysis")


def transcript_hash(cues: list[dict]) -> str:
    raw = "\n".join(f"{c['start_ms']}-{c['end_ms']}:{c['text']}" for c in cues)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AnalysisService:
    def __init__(self, vrepo: VideoRepo, srepo: SegmentRepo, sumrepo: SummaryRepo,
                 chrepo: ChapterRepo, krepo: KnowledgePointRepo, llm):
        self.videos = vrepo
        self.segments = srepo
        self.summaries = sumrepo
        self.chapters = chrepo
        self.points = krepo
        self.llm = llm

    def _cues(self, video_id: str, caption_id: str | None) -> list[dict]:
        return self.segments.for_video(video_id, caption_id)

    async def summarize(self, video_id: str, *, mode: str = "quick",
                        caption_id: str | None = None, content_scope: str = "unknown",
                        model: str = "", profile: dict | None = None) -> dict:
        cues = self._cues(video_id, caption_id)
        if not cues:
            raise ValueError("没有可用字幕，无法生成总结")
        ctx = ai.build_transcript_context(cues)
        title = self.videos.get(video_id)["title"]

        # 有职业档案时才要求模型给「职业发展建议」
        career = (profile or {}).get("career") or ""
        tags = (profile or {}).get("tags") or []
        goal = (profile or {}).get("goal") or ""
        industry = (profile or {}).get("industry") or ""
        has_profile = bool(career or tags or goal)

        if has_profile:
            who = "、".join([x for x in ([career] + list(tags)) if x])
            career_line = (f"我的职业：{who or '未填写'}\n"
                           f"所在行业：{industry or '未填写'}\n"
                           f"想达成的目标：{goal or '未填写'}\n")
            ask = ('请输出 {"one_liner":"一句话概括","key_points":["要点"],"terms":["术语"],'
                   '"audience":"适合人群","content_scope":"full|partial|unknown",'
                   '"career_advice":"结合我的职业给出的大白话职业发展建议"}')
            system = ai.SYSTEM_SUMMARY_CAREER
        else:
            career_line = ""
            ask = ('请输出 {"one_liner":"一句话概括","key_points":["要点"],"terms":["术语"],'
                   '"audience":"适合人群","content_scope":"full|partial|unknown"}')
            system = ai.SYSTEM_SUMMARY

        user = (f"视频标题：{title}\n"
                f"内容范围：{content_scope}\n{career_line}字幕：\n{ctx}\n\n{ask}")
        data = await self.llm.complete_json(system, user, ai.SUMMARY_SCHEMA)
        data["content_scope"] = content_scope  # 以系统判定为准，不信模型
        if not has_profile:
            data.pop("career_advice", None)
        s = self.summaries.add(video_id=video_id, mode=mode, content=data,
                               content_scope=content_scope, model=model, provider="llm",
                               prompt_version="v2" if has_profile else "v1",
                               transcript_hash=transcript_hash(cues),
                               plain_text=data.get("one_liner"))
        return s

    async def build_chapters(self, video_id: str, *, caption_id: str | None = None,
                             model: str = "") -> list[dict]:
        cues = self._cues(video_id, caption_id)
        if not cues:
            raise ValueError("没有可用字幕，无法生成章节")
        ctx = ai.build_transcript_context(cues)
        user = (f"视频标题：{self.videos.get(video_id)['title']}\n字幕：\n{ctx}\n\n"
                '请输出 {"chapters":[{"title":"","start_ms":0,"end_ms":0,"summary":""}]}，'
                "start_ms/end_ms 必须来自字幕里的真实时间戳。")
        data = await self.llm.complete_json(ai.SYSTEM_CHAPTERS, user, ai.CHAPTERS_SCHEMA)
        chs = ai.normalize_timestamps(data.get("chapters") or [], None, cues)
        chs = [c for c in chs if c.get("title")]
        self.chapters.replace_for_video(video_id, chs)
        return self.chapters.for_video(video_id)

    async def build_points(self, video_id: str, *, caption_id: str | None = None,
                           model: str = "") -> list[dict]:
        cues = self._cues(video_id, caption_id)
        if not cues:
            raise ValueError("没有可用字幕，无法生成知识点")
        ctx = ai.build_transcript_context(cues)
        user = (f"视频标题：{self.videos.get(video_id)['title']}\n字幕：\n{ctx}\n\n"
                '请输出 {"knowledge_points":[{"title":"","content":"","start_ms":0}]}，'
                "start_ms 若给必须来自字幕真实时间戳，否则不要给。")
        data = await self.llm.complete_json(ai.SYSTEM_POINTS, user, ai.POINTS_SCHEMA)
        pts = ai.normalize_timestamps(data.get("knowledge_points") or [], None, cues)
        pts = [p for p in pts if p.get("title")]
        self.points.replace_for_video(video_id, pts)
        return self.points.for_video(video_id)
