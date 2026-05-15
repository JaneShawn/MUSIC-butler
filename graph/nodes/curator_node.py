# -*- coding: utf-8 -*-
"""Curator Agent 节点 — 推荐策展与评估"""
import json
from typing import Dict, Any

from langgraph.prebuilt import create_react_agent

from graph.state import MusicAgentState
from graph.kimi_adapter import KimiChatModel
from graph.tools.curator_tools import CURATOR_TOOLS
from graph.utils import msg_content

CURATOR_SYSTEM_PROMPT = """你是音乐策展人，负责评估候选歌曲并生成个性化推荐。你的职责：

1. **评估推荐**：用 evaluate_recommendations 工具评估候选歌曲，生成推荐理由和评分
2. **周报**：用 generate_weekly_report 工具生成本周音乐发现摘要

你擅长根据用户的口味筛选好歌，并给出有感染力的推荐理由。以中文回复，保持专业且热情的策展风格。"""

_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        from graph.utils import load_config
        model = load_config().get("llm", {}).get("model", "moonshot-v1-8k")
        llm = KimiChatModel(model=model, temperature=0.5, max_tokens=1000)
        _agent = create_react_agent(
            model=llm,
            tools=CURATOR_TOOLS,
            prompt=CURATOR_SYSTEM_PROMPT,
        )
    return _agent


def curator_node(state: MusicAgentState) -> Dict[str, Any]:
    """Curator Agent 节点入口"""
    messages = state.get("messages", [])
    params = state.get("task_params", {})
    discoveries = state.get("discoveries", [])

    # 如果有后台的发现数据，直接评估
    input_text = ""
    if params.get("query"):
        input_text = params["query"]
    elif discoveries:
        discoveries_json = json.dumps(discoveries, ensure_ascii=False)
        input_text = f"请评估以下候选歌曲并生成推荐：\n{discoveries_json}"
    elif messages:
        input_text = msg_content(messages[-1])

    if not input_text:
        return {"final_response": "没有需要评估的歌曲。请先发现新音乐。",
                "agent_trace": state.get("agent_trace", []) + ["curator: no input"]}

    agent = _get_agent()
    result = agent.invoke({"messages": [("user", input_text)]})

    final_msgs = result.get("messages", [])
    assistant_reply = ""
    for msg in reversed(final_msgs):
        if hasattr(msg, "content") and msg.content:
            assistant_reply = msg.content
            break

    if not assistant_reply:
        assistant_reply = "推荐评估已完成！请查看推荐列表。"

    return {
        "final_response": assistant_reply,
        "agent_trace": state.get("agent_trace", []) + ["curator: done"],
    }
