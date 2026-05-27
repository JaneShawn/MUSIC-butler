# -*- coding: utf-8 -*-
"""Metadata Agent 节点 — ReAct agent，元数据诊断修复与标签管理

[Phase 3] 从纯过程式 metadata_node 升级为 ReAct agent。
LLM 自主决定调用哪个工具（diagnose/fix/update_tag/sync）。
"""
from typing import Dict, Any

from langgraph.prebuilt import create_react_agent

from graph.state import MusicAgentState
from graph.kimi_adapter import KimiChatModel
from graph.tools.metadata_tools import METADATA_TOOLS
from graph.utils import msg_content

METADATA_SYSTEM_PROMPT = """你是元数据管理专家，负责维护音乐库中每首歌的信息完整性。你的职责：

1. **诊断**：用 diagnose_metadata 工具检查音乐库元数据完整性
   - 告诉你缺什么：艺术家、标题、专辑、封面
2. **修复单首**：用 fix_single_song 工具在线搜索补全某首歌的元数据
   - file_hint 是文件名中的关键词
3. **批量修复**：用 fix_metadata_batch 工具批量处理
   - 必须先 preview（dry_run=True），用户确认后再执行（dry_run=False）
4. **标签纠正**：用 update_song_tag 工具修改某首歌的语言/情绪标签
   - field='language' 或 'emotion'
   - 用户说「标记XX为韩语」→ update_song_tag(song_hint='XX', field='language', value='韩语')
   - 用户说「标记YY为快乐的歌」→ update_song_tag(song_hint='YY', field='emotion', value='快乐')
5. **同步缓存**：用 sync_emotion_cache 工具将情绪缓存写入数据库

工作流程：
- 用户说「诊断元数据」→ diagnose_metadata
- 用户说「修复XX」→ fix_single_song(file_hint='XX')
- 用户说「一键修复」→ fix_metadata_batch(dry_run=True) 先预览
- 用户说「标记XX为YY」→ update_song_tag 纠正标签
- 用户说「同步情绪」→ sync_emotion_cache

批量修复和危险操作必须先预览再执行。以中文回复，保持简洁清晰。"""

_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        llm = KimiChatModel(model="moonshot-v1-8k", temperature=0.3, max_tokens=600)
        _agent = create_react_agent(
            model=llm,
            tools=METADATA_TOOLS,
            prompt=METADATA_SYSTEM_PROMPT,
        )
    return _agent


def metadata_agent_node(state: MusicAgentState) -> Dict[str, Any]:
    """Metadata ReAct Agent 节点入口"""
    messages = state.get("messages", [])
    trace = state.get("agent_trace", [])

    if not messages:
        return {
            "final_response": "请告诉我你想做什么元数据操作。",
            "agent_trace": trace + ["metadata: no input"],
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
        "final_response": assistant_reply or "元数据操作完成。",
        "agent_trace": trace + ["metadata: done"],
    }
