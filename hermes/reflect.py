# -*- coding: utf-8 -*-
"""
Hermes Reflect — 自进化反思引擎

每次 Agent 执行完毕后运行，提取：
  1. 用户偏好 → 写入 Memory
  2. 可复用的操作模式 → 沉淀为 Skill
  3. 纠正 → 修正错误记忆

不阻塞主流程，不增加用户感知延迟。
"""
import json
from typing import Any, Dict, List, Optional

from hermes.memory import get_memory_store, Memory
from hermes.skill import get_skill_store, Skill

# 不需要反思的意图（纯元操作）
_SKIP_INTENTS = {"help", "exit", "clear", "cancel", "greeting", "chitchat"}


class ReflectEngine:
    """反思引擎 — 分析 Agent 交互，提取记忆和技能。

    使用方式:
        engine = ReflectEngine()
        result = engine.reflect(user_input, agent_trace, final_response)
        # result → {"memories_added": 2, "skill_candidate": None}
    """

    def __init__(self, kimi_client=None):
        self._kimi = kimi_client

    def _get_kimi(self):
        if self._kimi is None:
            from core.kimi_client import KimiClient
            from graph.utils import load_config
            self._kimi = KimiClient(config=load_config())
        return self._kimi

    def reflect(
        self,
        user_input: str,
        intent: str,
        target_agent: str,
        agent_trace: List[str],
        final_response: str,
    ) -> Dict[str, Any]:
        """反思一次交互，提取记忆和技能。

        Returns:
            {"memories_added": int, "skill_candidate": Skill|None, "reflection": str}
        """
        result = {"memories_added": 0, "skill_candidate": None, "reflection": ""}

        # 跳过不需要反思的简单交互
        if intent in _SKIP_INTENTS:
            return result

        # 规则提取（快速路径，不走 LLM）
        extracted = _extract_rules(user_input, intent, target_agent, final_response)
        if extracted:
            for mtype, key, value in extracted:
                get_memory_store().upsert(mtype, key, value, confidence=0.6,
                                          source=f"reflect:{intent}")
                result["memories_added"] += 1

        # LLM 深度反思（异步路径，超出阈值时才调用）
        if _should_deep_reflect(intent, len(user_input)):
            try:
                deep = self._deep_reflect(user_input, intent, target_agent,
                                          agent_trace, final_response)
                if deep:
                    for mtype, key, value in deep.get("memories", []):
                        get_memory_store().upsert(mtype, key, value, confidence=0.7,
                                                  source=f"deep_reflect:{intent}")
                        result["memories_added"] += 1
                    if deep.get("skill"):
                        skill = Skill(
                            name=deep["skill"]["name"],
                            description=deep["skill"].get("description", ""),
                            trigger_keywords=deep["skill"].get("keywords", ""),
                            target_agent=target_agent,
                            intent=intent,
                        )
                        get_skill_store().register(skill)
                        result["skill_candidate"] = skill
                    result["reflection"] = deep.get("summary", "")
            except Exception:
                pass  # 反思失败不阻塞主流程

        return result

    def _deep_reflect(
        self, user_input: str, intent: str, target_agent: str,
        agent_trace: List[str], final_response: str,
    ) -> Optional[Dict[str, Any]]:
        """LLM 深度反思 — 只在值得反思的复杂交互上调用。"""
        kimi = self._get_kimi()

        prompt = f"""分析这次音乐助手交互，提取可学习的经验：

用户输入: {user_input}
路由意图: {intent}
执行Agent: {target_agent}
执行轨迹: {' → '.join(agent_trace[-5:]) if agent_trace else '无'}
助手回复: {final_response[:300]}

请提取（JSON格式）：
{{
  "memories": [
    ["preference", "like_artist", "周杰伦"],  // mtype, key, value
    ["fact", "user_language", "国语"]
  ],
  "skill": {{
    "name": "play_rock_songs",           // 技能名（英文snake_case）
    "description": "播放摇滚歌曲",         // 简短描述
    "keywords": "摇滚|rock|摇滚乐"         // 触发关键词（|分隔）
  }},
  "summary": "一句话总结这次交互"
}}

规则：
- 只提取明确观察到的偏好或事实，不要猜测
- 如果用户没有表达偏好，memories 可以为空数组
- skill 只在操作模式可复用且非通用时提取（如"播放摇滚"可提取，"播放晴天"太具体不提取）
- 返回纯JSON，不要包含markdown代码块标记"""

        response = kimi.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=500,
        )
        content = response.get("content", "") or ""
        # 清理可能的 markdown 包裹
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None


def _should_deep_reflect(intent: str, input_len: int) -> bool:
    """判断是否值得做 LLM 深度反思。"""
    # 只有复杂查询和播放类才做深度反思
    complex_intents = {
        "query", "search", "play_by_name", "play_by_artist",
        "play_all", "play_random", "query_emotion_songs",
        "query_language_songs", "recommend_random",
        "organize", "dedup", "fix_single", "fix_metadata",
        "correct_emotion", "correct_language",
    }
    return intent in complex_intents and input_len > 3


def _extract_rules(
    user_input: str, intent: str, target_agent: str, final_response: str,
) -> List[tuple]:
    """快速规则提取 — 不调用 LLM，纯模式匹配提取偏好。"""
    results = []

    # 检测语言偏好
    lang_keywords = {
        "国语": "国语", "中文": "国语", "普通话": "国语",
        "粤语": "粤语", "广东话": "粤语",
        "英语": "英语", "英文": "英语",
        "日语": "日语", "日文": "日语",
        "韩语": "韩语", "韩文": "韩语",
    }
    for kw, lang in lang_keywords.items():
        if kw in user_input and intent in ("query_language_songs", "play_random"):
            results.append(("preference", f"language:{lang}", f"用户搜索过{lang}歌曲"))

    # 检测情绪偏好
    emotion_kw = {
        "开心": "happy", "快乐": "happy", "悲伤": "sad", "难过": "sad",
        "安静": "calm", "平静": "calm", "激情": "energetic", "浪漫": "romantic",
    }
    for kw, em in emotion_kw.items():
        if kw in user_input and intent in ("query_emotion_songs", "play_random"):
            results.append(("preference", f"emotion:{em}", f"用户搜索过{kw}的歌曲"))

    # 检测歌手偏好
    if intent == "play_by_artist":
        # 从 user_input 提取歌手名（在 "播放" 和 "的歌" 之间）
        for prefix in ["播放", "放", "听"]:
            if user_input.startswith(prefix):
                rest = user_input[len(prefix):]
                for suffix in ["的歌", "的歌曲", "歌曲"]:
                    if rest.endswith(suffix):
                        artist = rest[:-len(suffix)].strip()
                        if artist and len(artist) >= 2:
                            results.append(("preference", f"like_artist:{artist}",
                                            f"用户听过{artist}的歌"))
                        break
                break

    return results
