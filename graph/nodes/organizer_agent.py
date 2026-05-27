# -*- coding: utf-8 -*-
"""Organizer Agent 节点 — ReAct agent，文件整理与去重

[Phase 3] 从纯过程式 organizer_node 升级为 ReAct agent。
LLM 自主决定调用哪个工具（organize/dedup/analyze），危险操作先预览再确认。
"""
from typing import Dict, Any

from langgraph.prebuilt import create_react_agent

from graph.state import MusicAgentState
from graph.kimi_adapter import KimiChatModel
from graph.tools.organizer_tools import ORGANIZER_TOOLS
from graph.utils import msg_content

ORGANIZER_SYSTEM_PROMPT = """你是文件整理专家，负责管理用户的音乐文件目录结构。你的职责：

1. **分析结构**：用 analyze_structure 工具分析当前目录结构，了解歌曲分布
2. **整理文件**：用 organize_files 工具按策略整理文件到规范目录
   - strategy 可选: 'artist/album'(默认), 'genre/artist', 'year/artist'
   - 危险操作！首次调用必须 dry_run=True 预览
   - 用户确认后设置 dry_run=False 执行
3. **检测重复**：用 dedup_files 工具查找重复歌曲
   - 首次调用 dry_run=True 仅列出
   - 确认后 dry_run=False 清理

工作流程：
- 用户说「整理」→ 先 analyze_structure，再 organize_files(dry_run=True) 预览
- 用户说「去重」→ dedup_files(dry_run=True) 预览
- 用户确认后 → 对应工具 dry_run=False 执行
- 用户说「分析目录」→ analyze_structure

危险操作（移动文件、删除文件）必须先预览，显示影响范围，
等用户明确确认后再执行。绝不允许跳过预览直接执行。

以中文回复，保持简洁清晰。"""

_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        llm = KimiChatModel(model="moonshot-v1-8k", temperature=0.3, max_tokens=600)
        _agent = create_react_agent(
            model=llm,
            tools=ORGANIZER_TOOLS,
            prompt=ORGANIZER_SYSTEM_PROMPT,
        )
    return _agent


def organizer_agent_node(state: MusicAgentState) -> Dict[str, Any]:
    """Organizer ReAct Agent 节点入口"""
    messages = state.get("messages", [])
    trace = state.get("agent_trace", [])

    if not messages:
        return {
            "final_response": "请告诉我你想怎么整理文件。",
            "agent_trace": trace + ["organizer: no input"],
        }

    user_input = msg_content(messages[-1])

    agent = _get_agent()
    result = agent.invoke({"messages": [("user", user_input)]})

    final_msgs = result.get("messages", [])
    assistant_reply = ""
    for msg in reversed(final_msgs):
        if hasattr(msg, "content") and msg.content:
            assistant_reply = msg.content
            break

    return {
        "final_response": assistant_reply or "整理操作完成。",
        "agent_trace": trace + ["organizer: done"],
    }
