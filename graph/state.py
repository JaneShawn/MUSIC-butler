# -*- coding: utf-8 -*-
"""MusicAgentState — 多Agent全局状态定义"""
from typing import TypedDict, List, Dict, Any, Optional, Annotated
from langgraph.graph.message import add_messages


class MusicAgentState(TypedDict):
    """音乐管家全局状态 — 在 Agent 节点间流转的共享数据结构"""
    messages: Annotated[List[Dict[str, Any]], add_messages]
    intent: str
    task_params: Dict[str, Any]
    query_results: List[Dict[str, Any]]
    discoveries: List[Dict[str, Any]]
    recommendations: List[Dict[str, Any]]
    pending_action: Optional[Dict[str, Any]]
    requires_confirmation: bool
    final_response: str
    agent_trace: List[str]
