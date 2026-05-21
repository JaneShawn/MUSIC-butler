# -*- coding: utf-8 -*-
"""主图构建 — StateGraph 定义、节点注册、边连接、编译"""
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from graph.state import MusicAgentState
from graph.nodes import (
    intent_router_node,
    librarian_node,
    organizer_node,
    metadata_node,
    respond_node,
)
from graph.router import route_by_intent


def build_graph() -> StateGraph:
    """构建并编译 Music Agent 多Agent 图"""

    workflow = StateGraph(MusicAgentState)

    # 注册节点
    workflow.add_node("intent_router", intent_router_node)
    workflow.add_node("librarian", librarian_node)
    workflow.add_node("organizer", organizer_node)
    workflow.add_node("metadata", metadata_node)
    workflow.add_node("respond", respond_node)

    # 起始边：START → intent_router
    workflow.add_edge(START, "intent_router")

    # 条件路由：intent_router 根据意图分发
    workflow.add_conditional_edges(
        "intent_router",
        route_by_intent,
        {
            "librarian": "librarian",
            "organizer": "organizer",
            "metadata": "metadata",
            "respond": "respond",
        }
    )

    # Agent 完成后 → respond 格式化回复
    workflow.add_edge("librarian", "respond")
    workflow.add_edge("organizer", "respond")
    workflow.add_edge("metadata", "respond")

    # 结束
    workflow.add_edge("respond", END)

    # 编译 — MemorySaver 自动持久化会话（替代 chat_session.json）
    memory = MemorySaver()
    app = workflow.compile(checkpointer=memory)
    return app


# 全局单例
music_graph = build_graph()
