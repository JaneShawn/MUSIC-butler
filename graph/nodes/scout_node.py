# -*- coding: utf-8 -*-
"""Scout Agent 节点 — 外部音乐发现"""
import json
from typing import Dict, Any

from langgraph.prebuilt import create_react_agent

from graph.state import MusicAgentState
from graph.kimi_adapter import KimiChatModel
from graph.tools.scout_tools import SCOUT_TOOLS
from graph.utils import msg_content

SCOUT_SYSTEM_PROMPT = """你是音乐侦察兵，负责从外部源发现新音乐。你的职责：

1. **RSS/Reddit 发现**：用 discover_from_sources 工具从 RSS 订阅和 Reddit 社区获取最新音乐
2. **相似艺术家**：用 discover_similar_artist 工具找与指定艺术家风格相似的歌
3. **场景音乐**：用 discover_by_mood 工具找适合特定场景（工作/学习/运动/放松）的音乐
4. **新发行**：用 discover_artist_new 工具查艺术家的最新发行

发现音乐后，将结果整理好返回给用户。以中文回复，保持热情和专业的风格。"""

_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        from graph.utils import load_config
        model = load_config().get("llm", {}).get("model", "moonshot-v1-8k")
        llm = KimiChatModel(model=model, temperature=0.5, max_tokens=1000)
        _agent = create_react_agent(
            model=llm,
            tools=SCOUT_TOOLS,
            prompt=SCOUT_SYSTEM_PROMPT,
        )
    return _agent


def scout_node(state: MusicAgentState) -> Dict[str, Any]:
    """Scout Agent 节点入口"""
    messages = state.get("messages", [])
    params = state.get("task_params", {})

    if not messages:
        return {"final_response": "请告诉我你想发现什么样的音乐。",
                "agent_trace": state.get("agent_trace", []) + ["scout: no input"]}

    user_input = msg_content(messages[-1])

    agent = _get_agent()
    result = agent.invoke({"messages": [("user", user_input)]})

    final_msgs = result.get("messages", [])
    assistant_reply = ""
    for msg in reversed(final_msgs):
        if hasattr(msg, "content") and msg.content:
            assistant_reply = msg.content
            break

    if not assistant_reply:
        assistant_reply = "音乐发现完成！请查看结果。"

    return {
        "final_response": assistant_reply,
        "agent_trace": state.get("agent_trace", []) + ["scout: done"],
    }
