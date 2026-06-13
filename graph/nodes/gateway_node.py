# -*- coding: utf-8 -*-
"""
Hermes Gateway 节点 — 将 HermesGateway 接入 LangGraph

采用纯 LLM Function Calling 决策。

[Phase 4] 路由前查询 Memory + Skill 注入上下文，实现闭环反哺。
"""
from typing import Any, Dict, Optional

from graph.state import MusicAgentState
from graph.utils import msg_content
from hermes.gateway import HermesGateway

_gateway: Optional[HermesGateway] = None


def _get_gateway() -> HermesGateway:
    global _gateway
    if _gateway is None:
        _gateway = HermesGateway()
    return _gateway


def gateway_node(state: MusicAgentState) -> Dict[str, Any]:
    """Hermes Gateway 节点 — 解析用户意图，决定 Agent 分发。

    输入:  state.messages (取最后一条用户消息)
    输出:  intent, target_agent, task_params, agent_trace,
           memory_context, skill_match, final_response (如果是直接回复)
    """
    messages = state.get("messages", [])
    if not messages:
        return {
            "intent": "respond", "target_agent": "respond",
            "task_params": {}, "final_response": "",
            "memory_context": "", "skill_match": "",
            "agent_trace": ["gateway: 无消息"],
        }

    user_input = msg_content(messages[-1]).strip()
    if not user_input:
        return {
            "intent": "respond", "target_agent": "respond",
            "task_params": {}, "final_response": "",
            "memory_context": "", "skill_match": "",
            "agent_trace": ["gateway: 空输入"],
        }

    # 提取上一轮 assistant 消息，作为路由上下文（解决用户简短回复误路由问题）
    last_assistant = ""
    for m in reversed(messages[:-1]):
        role = m.get("role", "") if isinstance(m, dict) else getattr(m, "role", "")
        mtype = m.get("type", "") if isinstance(m, dict) else getattr(m, "type", "")
        if role == "assistant" or mtype == "ai":
            content = msg_content(m)
            if content and len(content) > 5:
                last_assistant = content
                break

    # ── 闭环反哺：查询记忆和技能 ──
    memory_context = ""
    skill_match = ""
    try:
        from hermes.memory import get_memory_store
        memories = get_memory_store().query_relevant(user_input, limit=5)
        if memories:
            memory_context = "\n".join(
                f"- {m.key}: {m.value}" for m in memories
            )
    except Exception:
        pass

    # 路由（Gateway 内部会先查 Skill 缓存，再走 LLM）
    gateway = _get_gateway()
    decision = gateway.route(user_input, memory_context=memory_context,
                             last_assistant=last_assistant)

    # 如果 Skill 命中，记录
    if decision.agent_trace.startswith("gateway(skill)"):
        skill_match = decision.reasoning.replace("skill match: ", "")

    result: Dict[str, Any] = {
        "intent": decision.intent,
        "target_agent": decision.target_agent,
        "task_params": decision.task_params,
        "final_response": "",
        "memory_context": memory_context,
        "skill_match": skill_match,
        "agent_trace": [decision.agent_trace],
    }

    # respond_directly 的回复直接写入 final_response
    if decision.target_agent == "respond" and decision.direct_response:
        result["final_response"] = decision.direct_response

    return result
