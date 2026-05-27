# -*- coding: utf-8 -*-
"""
Reflect 节点 — 自进化闭环入口

Agent 执行完毕后运行，提取记忆和技能，不阻塞响应流。
"""
from typing import Any, Dict

from graph.state import MusicAgentState
from graph.utils import msg_content


def reflect_node(state: MusicAgentState) -> Dict[str, Any]:
    """Reflect 节点 — 从交互中提取经验，沉淀到 Memory 和 Skill 库。

    输入:  state.messages, state.intent, state.target_agent,
           state.agent_trace, state.final_response
    输出:  agent_trace（追加 reflect 日志）
    """
    intent = state.get("intent", "")
    target_agent = state.get("target_agent", "")
    agent_trace = state.get("agent_trace", [])
    final_response = state.get("final_response", "")
    messages = state.get("messages", [])

    user_input = msg_content(messages[-1]) if messages else ""

    # 无有效输入时跳过
    if not user_input:
        return {"agent_trace": agent_trace + ["reflect: skipped (empty)"]}

    try:
        from hermes.reflect import ReflectEngine
        engine = ReflectEngine()
        result = engine.reflect(
            user_input=user_input,
            intent=intent,
            target_agent=target_agent,
            agent_trace=agent_trace,
            final_response=final_response,
        )

        trace_line = (
            f"reflect: +{result['memories_added']} memories"
            + (f", skill={result['skill_candidate'].name}" if result['skill_candidate'] else "")
        )
        return {"agent_trace": agent_trace + [trace_line]}

    except Exception as e:
        return {"agent_trace": agent_trace + [f"reflect: error ({e})"]}
