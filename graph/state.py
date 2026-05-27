# -*- coding: utf-8 -*-
"""MusicAgentState — 多Agent全局状态定义"""
from typing import TypedDict, List, Dict, Any, Optional, Annotated
from langgraph.graph.message import add_messages


class MusicAgentState(TypedDict):
    """音乐管家全局状态 — 在 Agent 节点间流转的共享数据结构

    [Phase 2] target_agent: Hermes Gateway 选中的目标 agent 节点名。
    [Phase 4] memory_context: Hermes Gateway 注入的相关记忆上下文。
              memory_updates: Reflect 节点新增的记忆，供下一轮 Gateway 使用。
    """
    messages: Annotated[List[Dict[str, Any]], add_messages]
    intent: str
    target_agent: str
    task_params: Dict[str, Any]
    query_results: List[Dict[str, Any]]
    discoveries: List[Dict[str, Any]]
    recommendations: List[Dict[str, Any]]
    pending_action: Optional[Dict[str, Any]]
    requires_confirmation: bool
    final_response: str
    agent_trace: List[str]
    memory_context: str
    skill_match: str
