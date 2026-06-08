# -*- coding: utf-8 -*-
"""
Hermes Gateway 层 — 纯 LLM 路由网关

职责：接收 TriggerEvent → LLM Function Calling → 决定分发给哪个 Agent

与旧 intent_router 的关键区别：
  - 不做硬编码关键词匹配（无 L0/L1/L3）
  - 只有 4 个 agent 级 dispatch function（不是 32 个细粒度 tool）
  - 每个 dispatch 带 reasoning 字段，透明可审计
  - 极简 fallback：exit/help/clear 三个 meta 命令直接命中，其余全部 LLM 决策
"""
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from hermes.trigger import TriggerEvent

# ── Agent 调度 schema（4 个 agent，替代旧的 32 个 tool） ─────

GATEWAY_DISPATCH_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "dispatch_to_librarian",
            "description": (
                "音乐库搜索、查询、播放、统计、情绪分析、语言检测。"
                "用户想找歌、播放歌曲、随机推荐、查看库状态、按情绪/语言筛选时选此。"
                "例如：'播放晴天'、'有哪些韩语歌'、'随机播放五首开心的歌'、'扫描音乐库'、'语言分布'、'分析情绪'。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": (
                            "具体操作: query, search, play_by_name, play_by_artist, "
                            "play_all, play_random, scan, show_language_stats, "
                            "analyze_emotion, show_library_stats, query_emotion_songs, "
                            "query_language_songs, clear_emotion_cache, recommend_random"
                        ),
                    },
                    "query": {"type": "string", "description": "搜索关键词或自然语言查询"},
                    "song_name": {"type": "string", "description": "歌曲名"},
                    "artist": {"type": "string", "description": "歌手/艺术家名"},
                    "language": {"type": "string", "description": "语言: 国语/英语/粤语/日语/韩语"},
                    "emotion": {"type": "string", "description": "情绪: happy/sad/calm/energetic/romantic/nostalgic/angry/focus/party"},
                    "count": {"type": "integer", "description": "播放/推荐数量"},
                    "force": {"type": "boolean", "description": "是否强制重新分析"},
                    "reasoning": {"type": "string", "description": "为什么选择 librarian agent"},
                },
                "required": ["intent", "reasoning"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dispatch_to_organizer",
            "description": (
                "文件整理、去重、目录结构分析。"
                "用户想整理音乐文件、清理重复歌曲、分析目录结构时选此。"
                "例如：'整理音乐'、'去重'、'分析目录结构'。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "具体操作: organize, dedup, analyze",
                    },
                    "strategy": {"type": "string", "description": "整理策略: artist/album, genre/artist, year/artist"},
                    "reasoning": {"type": "string", "description": "为什么选择 organizer agent"},
                },
                "required": ["intent", "reasoning"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dispatch_to_metadata",
            "description": (
                "元数据修复、诊断、情绪/语言标签纠正、单曲分析、音频格式转换。"
                "用户想修复歌曲信息、诊断元数据问题、纠正标签、转换音频格式时选此。"
                "例如：'诊断元数据'、'修复晴天'、'标记BTS为韩语'、'同步情绪缓存'、'转换格式'。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": (
                            "具体操作: diagnose, fix_single, fix_metadata, fix_metadata_issues, "
                            "sync_emotion, correct_emotion, correct_language, update_song_info, "
                            "detect_single_language, analyze_single_emotion, convert"
                        ),
                    },
                    "song_hint": {"type": "string", "description": "歌曲名或关键词"},
                    "field": {"type": "string", "description": "要更新的字段: language/emotion/genre/artist/album"},
                    "value": {"type": "string", "description": "新值"},
                    "target_format": {"type": "string", "description": "转换目标格式: mp3 或 flac（用户指定时提取）"},
                    "reasoning": {"type": "string", "description": "为什么选择 metadata agent"},
                },
                "required": ["intent", "reasoning"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "respond_directly",
            "description": (
                "闲聊、帮助、退出、取消、模型管理、导入导出等不需要复杂业务逻辑的请求。"
                "用户只是打招呼、问功能、切换设置时选此。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": (
                            "具体操作: help, exit, clear, cancel, list_playlists, "
                            "list_models, switch_model, current_model, "
                            "export_library, import_library, greeting, chitchat"
                        ),
                    },
                    "message": {"type": "string", "description": "直接回复内容（用于 greeting/chitchat/help）"},
                    "reasoning": {"type": "string", "description": "为什么选择直接回复"},
                },
                "required": ["intent", "reasoning"],
            },
        },
    },
]

# ── 极简 meta 命令映射（仅 3 个，不走 LLM） ────────────────

_META_COMMANDS = {
    "退出": ("exit", {}),
    "exit": ("exit", {}),
    "quit": ("exit", {}),
    "再见": ("exit", {}),
    "886": ("exit", {}),
    "帮助": ("help", {}),
    "help": ("help", {}),
    "功能": ("help", {}),
    "能做什么": ("help", {}),
    "清除": ("clear", {}),
    "清空": ("clear", {}),
    "重置": ("clear", {}),
    "clear": ("clear", {}),
}

# ── Agent 名称映射 ──────────────────────────────────────────

_DISPATCH_TO_AGENT = {
    "dispatch_to_librarian": "librarian",
    "dispatch_to_organizer": "organizer",
    "dispatch_to_metadata": "metadata",
    "respond_directly": "respond",
}

# ── RouteDecision ───────────────────────────────────────────

@dataclass
class RouteDecision:
    """Gateway 路由决策结果"""
    target_agent: str                          # "librarian" | "organizer" | "metadata" | "respond"
    intent: str                                # 具体操作名
    task_params: Dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    direct_response: str = ""                  # respond_directly 时的直接回复
    agent_trace: str = ""


# ── HermesGateway ───────────────────────────────────────────

class HermesGateway:
    """纯 LLM 路由网关 — 一次 FC 调用决定 Agent 分发。

    使用方式:
        gateway = HermesGateway(kimi_client)
        decision = gateway.route(user_input)
        # decision.target_agent → "librarian"
        # decision.intent → "play_by_name"
        # decision.task_params → {"song_name": "晴天"}

    [Phase 4] route_with_context() 在路由前注入 Memory + Skill，
    实现闭环反哺：上次 Reflect 提取的经验影响下次 Gateway 决策。
    """

    def __init__(self, kimi_client=None):
        self._kimi = kimi_client  # 延迟初始化，允许 None

    def _get_kimi(self):
        if self._kimi is None:
            from core.kimi_client import KimiClient
            from graph.utils import load_config
            self._kimi = KimiClient(config=load_config())
        return self._kimi

    def route(self, user_input: str, memory_context: str = "", skill_match: str = "",
              last_assistant: str = "") -> RouteDecision:
        """解析用户输入，返回分发决策。

        Args:
            user_input: 用户输入文本
            memory_context: 从 MemoryStore 查询到的相关记忆（可选）
            skill_match: 从 SkillStore 匹配到的技能名（可选）
            last_assistant: 上一轮助手的回复内容，用于理解上下文（如 agent 刚问了格式选择）
        """
        stripped = user_input.strip()

        # L0: Skill 快速匹配（技能缓存命中时跳过 LLM）
        if not skill_match:
            from hermes.skill import get_skill_store
            matched = get_skill_store().match(stripped)
            if matched:
                return RouteDecision(
                    target_agent=matched.target_agent,
                    intent=matched.intent,
                    task_params={},
                    reasoning=f"skill match: {matched.name}",
                    agent_trace=f"gateway(skill): {matched.name} → {matched.intent}",
                )

        # L1: 极简 meta 命令（仅 exit/help/clear）
        if stripped in _META_COMMANDS:
            intent, params = _META_COMMANDS[stripped]
            return RouteDecision(
                target_agent="respond",
                intent=intent,
                task_params=params,
                reasoning=f"meta command: {stripped}",
                agent_trace=f"gateway(L0): {intent}",
            )

        # 主路径: LLM Function Calling
        try:
            return self._llm_route(user_input, memory_context, last_assistant)
        except Exception:
            return RouteDecision(
                target_agent="respond",
                intent="chitchat",
                task_params={"query": user_input},
                reasoning="LLM unavailable, fallback to respond",
                agent_trace="gateway(fallback): respond",
            )

    def _llm_route(self, user_input: str, memory_context: str = "",
                   last_assistant: str = "") -> RouteDecision:
        """调用 LLM 进行 agent 级路由。注入记忆和对话上下文辅助决策。"""
        kimi = self._get_kimi()

        system_prompt = (
            "你是 Hermes 路由网关，负责将用户的音乐管理请求分发给正确的 Agent。\n\n"
            "可用的 Agent：\n"
            "  - librarian: 音乐库搜索、查询、播放、统计、情绪分析\n"
            "  - organizer: 文件整理、去重、目录分析\n"
            "  - metadata: 元数据修复、诊断、标签纠正、格式转换\n"
            "  - respond: 直接文本回复（闲聊、帮助、设置等）\n\n"
            "规则：\n"
            "1. 用户有明确业务操作意图 → 分发给对应 agent\n"
            "2. 用户只是闲聊/问功能 → respond_directly\n"
            "3. 不确定时宁可 respond_directly 也不要猜\n"
            "4. reasoning 字段用中文写一句简短理由\n"
            "5. 重要：如果上一轮助手问了选择题（如'MP3还是FLAC'），用户回复的简短答案"
            "（如'flac'、'mp3'、'是'、'好的'）应视为对上轮操作的确认，分发给上轮对应的 agent"
        )

        # 注入记忆上下文
        if memory_context:
            system_prompt += f"\n\n[用户偏好记忆]\n{memory_context}"

        # 注入对话上下文：上一轮 agent 说了什么
        if last_assistant:
            system_prompt += f"\n\n[上一轮助手说了]\n{last_assistant}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]

        response = kimi.chat_completion(
            messages=messages,
            tools=GATEWAY_DISPATCH_SCHEMA,
            tool_choice="auto",
            temperature=0.1,
            max_tokens=300,
        )

        tool_calls = response.get("tool_calls")
        if not tool_calls or len(tool_calls) == 0:
            # LLM 选择不调用任何函数 → 直接回复
            content = response.get("content", "") or ""
            return RouteDecision(
                target_agent="respond",
                intent="chitchat",
                task_params={"query": user_input},
                reasoning="LLM chose not to dispatch",
                direct_response=content,
                agent_trace="gateway(LLM): respond (no tool_call)",
            )

        tc = tool_calls[0]
        func = tc.get("function", {})
        func_name = func.get("name", "respond_directly")

        try:
            args = json.loads(func.get("arguments", "{}"))
        except (json.JSONDecodeError, TypeError):
            args = {}

        target_agent = _DISPATCH_TO_AGENT.get(func_name, "respond")
        intent = args.get("intent", "chitchat")
        reasoning = args.get("reasoning", "")

        # 构建 task_params（剔除 intent/reasoning/message 元字段）
        task_params = {k: v for k, v in args.items()
                       if k not in ("intent", "reasoning", "message") and v}

        direct_response = args.get("message", "")

        return RouteDecision(
            target_agent=target_agent,
            intent=intent,
            task_params=task_params,
            reasoning=reasoning,
            direct_response=direct_response,
            agent_trace=f"gateway(LLM): {func_name} → {intent} ({reasoning})",
        )
