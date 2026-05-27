# -*- coding: utf-8 -*-
"""
Hermes Skill — 技能沉淀与快速匹配

将已验证的路由决策沉淀为 Skill，下次类似请求时直接命中，省去 LLM 调用。
"""
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class Skill:
    """一个已验证的操作技能"""
    name: str                   # "play_artist_songs"
    description: str            # "播放某歌手的歌"
    trigger_keywords: str       # "播放 X的歌|放 X|听 X的歌"
    target_agent: str           # "librarian"
    intent: str                 # "play_by_artist"
    success_count: int = 0
    last_used: str = ""


class SkillStore:
    """基于内存的技能库，快速模式匹配。

    使用方式:
        store = get_skill_store()
        match = store.match("播放周杰伦的歌")
        # match → Skill(target_agent="librarian", intent="play_by_artist", ...)
    """

    def __init__(self):
        self._skills: List[Skill] = []
        self._lock = threading.Lock()
        self._init_builtins()

    def _init_builtins(self):
        """初始化内置技能模板。这些是高频模式，直接匹配跳过 LLM。"""
        builtins = [
            Skill(
                name="play_by_artist",
                description="播放指定歌手的所有歌曲",
                trigger_keywords="播放{artist}的歌|放{artist}的歌|听{artist}|来首{artist}的|{artist}的歌",
                target_agent="librarian",
                intent="play_by_artist",
                success_count=10,
            ),
            Skill(
                name="query_language",
                description="查询/播放特定语言的歌曲",
                trigger_keywords="有哪些{language}歌|{language}歌|所有{language}歌|播放{language}歌|{language}歌曲",
                target_agent="librarian",
                intent="query_language_songs",
                success_count=10,
            ),
            Skill(
                name="query_emotion",
                description="查询/播放特定情绪的歌曲",
                trigger_keywords="有哪些{emotion}的歌|{emotion}的歌|所有{emotion}的歌|播放{emotion}的歌",
                target_agent="librarian",
                intent="query_emotion_songs",
                success_count=10,
            ),
            Skill(
                name="play_by_name",
                description="播放指定歌名的歌曲",
                trigger_keywords="播放{song}|放{song}|听{song}|来首{song}",
                target_agent="librarian",
                intent="play_by_name",
                success_count=10,
            ),
            Skill(
                name="dedup",
                description="检测并清理重复歌曲",
                trigger_keywords="去重|重复|清理重复|找重复",
                target_agent="organizer",
                intent="dedup",
                success_count=10,
            ),
            Skill(
                name="organize",
                description="整理音乐文件",
                trigger_keywords="整理|整理音乐|整理文件|组织目录",
                target_agent="organizer",
                intent="organize",
                success_count=10,
            ),
            Skill(
                name="diagnose",
                description="诊断元数据完整性",
                trigger_keywords="诊断|诊断元数据|元数据诊断|检查元数据|元数据完整性",
                target_agent="metadata",
                intent="diagnose",
                success_count=10,
            ),
            Skill(
                name="scan",
                description="扫描音乐库",
                trigger_keywords="扫描|扫描音乐库|更新音乐库|重新扫描",
                target_agent="librarian",
                intent="scan",
                success_count=10,
            ),
            Skill(
                name="play_all",
                description="播放全部歌曲",
                trigger_keywords="播放全部|播放所有|全部播放|所有歌曲",
                target_agent="librarian",
                intent="play_all",
                success_count=10,
            ),
        ]
        with self._lock:
            self._skills = builtins

    def match(self, user_input: str) -> Optional[Skill]:
        """快速匹配已知技能。匹配成功则返回 Skill，否则 None。

        匹配策略（两遍扫描）：
          1. 先扫描所有精确匹配（无占位符，包含即命中）
          2. 再扫描模板匹配（有 {placeholder}，前后缀匹配）
          3. 精确匹配优先于模板匹配，避免「播放全部」被「播放{song}」误吃
        """
        inp = user_input.strip()
        with self._lock:
            skills_sorted = sorted(self._skills, key=lambda s: (-s.success_count, -len(s.trigger_keywords)))

            # 第一遍：精确匹配
            for skill in skills_sorted:
                for pat in skill.trigger_keywords.split("|"):
                    pat = pat.strip()
                    if "{" not in pat and (pat in inp or inp == pat):
                        skill.last_used = datetime.now().isoformat()
                        return skill

            # 第二遍：模板匹配
            for skill in skills_sorted:
                for pat in skill.trigger_keywords.split("|"):
                    pat = pat.strip()
                    if "{" in pat and _template_match(pat, inp):
                        skill.last_used = datetime.now().isoformat()
                        return skill
        return None


_PLACEHOLDERS = ["{artist}", "{language}", "{emotion}", "{song}"]


def _template_match(pattern: str, text: str) -> bool:
    """模板匹配：{placeholder} 匹配任意非空内容。

    Example:
        _template_match("播放 {artist} 的歌", "播放周杰伦的歌") → True
        _template_match("播放 {song}", "播放晴天") → True
    """
    # 找到第一个占位符
    for ph in _PLACEHOLDERS:
        idx = pattern.find(ph)
        if idx >= 0:
            prefix = pattern[:idx]
            suffix = pattern[idx + len(ph):]
            if text.startswith(prefix) and text.endswith(suffix):
                middle = text[len(prefix):len(text) - len(suffix)] if suffix else text[len(prefix):]
                return len(middle) > 0
    return False

    def register(self, skill: Skill) -> None:
        """注册新技能或增加已有技能的计数。"""
        with self._lock:
            for s in self._skills:
                if s.name == skill.name:
                    s.success_count += 1
                    s.last_used = datetime.now().isoformat()
                    return
            skill.success_count = 1
            skill.last_used = datetime.now().isoformat()
            self._skills.append(skill)

    def list_all(self) -> List[Skill]:
        """列出所有已注册技能。"""
        with self._lock:
            return list(self._skills)


_store: Optional[SkillStore] = None


def get_skill_store() -> SkillStore:
    """获取全局 SkillStore 单例。"""
    global _store
    if _store is None:
        _store = SkillStore()
    return _store
