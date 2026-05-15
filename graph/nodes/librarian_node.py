# -*- coding: utf-8 -*-
"""Librarian Agent 节点 — 音乐库管理与搜索"""
import json
from typing import Dict, Any

from langgraph.prebuilt import create_react_agent

from graph.state import MusicAgentState
from graph.kimi_adapter import KimiChatModel
from graph.tools.library_tools import LIBRARIAN_TOOLS
from graph.utils import msg_content


LIBRARIAN_SYSTEM_PROMPT = """你是音乐图书管理员，负责管理用户的本地音乐库。你的职责：

1. **搜索歌曲**：用 search_music 工具语义搜索音乐库，理解自然语言查询（如"周杰伦的歌"、"90年代摇滚"）
2. **扫描库**：用 scan_library 工具扫描音乐目录，发现新文件
3. **查询详情**：用 get_song_info 获取特定歌曲的完整元数据
4. **库统计**：用 get_library_stats 获取整体统计
5. **播放歌曲**：用 play_song 工具播放指定歌名
6. **播放全部**：用 play_all_songs 工具播放整个音乐库
7. **播放歌手**：用 play_by_artist 工具播放某个歌手的所有歌曲
8. **播放语言**：用 play_by_language 工具播放指定语言的所有歌曲
9. **播放情绪**：用 play_by_emotion 工具播放指定情绪的所有歌曲

当用户要播放歌曲时，选择合适的播放工具：
- "播放晴天" → play_song
- "播放所有歌曲" / "播放全部" → play_all_songs
- "播放周杰伦的歌" → play_by_artist
- "播放所有英文歌" / "播放英语歌" → play_by_language(language="英语")
- "播放开心的歌" / "播放安静的歌曲" → play_by_emotion(emotion="happy"/"calm")
- "播放" + 具体歌名 → play_song

以中文回复用户，保持简洁友好。"""

_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        from graph.utils import load_config
        model = load_config().get("llm", {}).get("model", "moonshot-v1-8k")
        llm = KimiChatModel(model=model, temperature=0.3, max_tokens=800)
        _agent = create_react_agent(
            model=llm,
            tools=LIBRARIAN_TOOLS,
            prompt=LIBRARIAN_SYSTEM_PROMPT,
        )
    return _agent


def librarian_node(state: MusicAgentState) -> Dict[str, Any]:
    """Librarian Agent 节点入口"""
    intent = state.get("intent", "query")
    params = state.get("task_params", {})
    messages = state.get("messages", [])

    if not messages:
        return {
            "final_response": "请告诉我你想做什么。",
            "agent_trace": state.get("agent_trace", []) + ["librarian: no input"],
        }

    user_input = msg_content(messages[-1])

    agent = _get_agent()
    result = agent.invoke({"messages": [("user", user_input)]})

    # 提取 Agent 最终回复
    final_msgs = result.get("messages", [])
    assistant_reply = ""
    for msg in reversed(final_msgs):
        if hasattr(msg, "content") and msg.content:
            assistant_reply = msg.content
            break

    if not assistant_reply:
        assistant_reply = "搜索完成，请在结果中查看。"

    return {
        "final_response": assistant_reply,
        "agent_trace": state.get("agent_trace", []) + ["librarian: done"],
    }
