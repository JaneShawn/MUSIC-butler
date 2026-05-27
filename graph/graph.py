# -*- coding: utf-8 -*-
"""主图构建 — StateGraph 定义、节点注册、边连接、编译

[Phase 4] Hermes 完整拓扑:
  START → gateway → {librarian/organizer/metadata/respond}
       → reflect → respond → END

  闭环: Reflect 提取的记忆/技能反哺下一次 Gateway 路由。
"""
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from graph.state import MusicAgentState
from graph.nodes import (
    gateway_node,
    librarian_node,
    organizer_agent_node,
    metadata_agent_node,
    reflect_node,
    respond_node,
)
from graph.router import route_by_intent


def build_graph() -> StateGraph:
    """构建并编译 Music Agent 多Agent 图"""

    workflow = StateGraph(MusicAgentState)

    # 注册节点
    workflow.add_node("hermes_gateway", gateway_node)
    workflow.add_node("librarian", librarian_node)
    workflow.add_node("organizer", organizer_agent_node)
    workflow.add_node("metadata", metadata_agent_node)
    workflow.add_node("reflect", reflect_node)
    workflow.add_node("respond", respond_node)

    # 起始边：START → hermes_gateway
    workflow.add_edge(START, "hermes_gateway")

    # 条件路由：gateway 根据意图分发到对应 Agent
    workflow.add_conditional_edges(
        "hermes_gateway",
        route_by_intent,
        {
            "librarian": "librarian",
            "organizer": "organizer",
            "metadata": "metadata",
            "respond": "respond",
        }
    )

    # Agent → Reflect（闭环入口）
    workflow.add_edge("librarian", "reflect")
    workflow.add_edge("organizer", "reflect")
    workflow.add_edge("metadata", "reflect")

    # Reflect → Respond（格式化输出）
    workflow.add_edge("reflect", "respond")

    # respond 直接到结束（无需再 reflect）
    workflow.add_edge("respond", END)

    # 编译 — MemorySaver 自动持久化会话
    memory = MemorySaver()
    app = workflow.compile(checkpointer=memory)
    return app


# 全局单例
music_graph = build_graph()
