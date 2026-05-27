# -*- coding: utf-8 -*-
"""
[DEPRECATED] Organizer Agent 节点 — 文件整理与去重（过程式 if/elif）

Phase 3 起已由 organizer_agent.py (ReAct agent) 替代。
保留此文件仅作参考，不再被 graph 引用。
"""
from typing import Dict, Any

from graph.state import MusicAgentState
from graph.tools.organizer_tools import organize_files, dedup_files, analyze_structure
from graph.utils import msg_content


def organizer_node(state: MusicAgentState) -> Dict[str, Any]:
    """Organizer Agent 节点 — 处理文件整理和去重任务"""
    intent = state.get("intent", "")
    params = state.get("task_params", {})
    messages = state.get("messages", [])

    user_input = ""
    if messages:
        user_input = msg_content(messages[-1])

    trace = state.get("agent_trace", []) + ["organizer: running"]

    # 去重
    if intent == "dedup":
        result = dedup_files.invoke({"dry_run": True})
        return {
            "final_response": f"🔍 重复文件检测结果：\n{result}",
            "agent_trace": trace,
        }

    # 结构分析
    if intent == "analyze" and "整理" not in user_input and "organize" not in user_input.lower():
        result = analyze_structure.invoke({})
        return {
            "final_response": f"📊 音乐库结构分析：\n{result}",
            "agent_trace": trace,
        }

    # 文件整理（默认预览模式，危险操作需要确认）
    if state.get("requires_confirmation") and state.get("pending_action"):
        # 用户已确认，执行
        strategy = params.get("strategy", "artist/album")
        result = organize_files.invoke({"strategy": strategy, "dry_run": False})
        return {
            "final_response": f"✅ 文件整理完成！\n{result}",
            "agent_trace": trace + ["organizer: executed"],
        }

    # 首次请求：预览
    strategy = params.get("strategy", "artist/album")
    result = organize_files.invoke({"strategy": strategy, "dry_run": True})
    return {
        "final_response": f"📋 整理计划预览（未执行）：\n{result}\n\n⚠️ 确认执行请回复'确认'，取消请回复'取消'。",
        "requires_confirmation": True,
        "pending_action": {"action_type": "organize", "params": params, "description": "执行文件整理"},
        "agent_trace": trace + ["organizer: awaiting confirmation"],
    }
