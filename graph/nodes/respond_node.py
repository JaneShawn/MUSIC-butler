# -*- coding: utf-8 -*-
"""Respond 节点 — 格式化最终回复并处理简单指令"""
from typing import Dict, Any

from graph.state import MusicAgentState


def respond_node(state: MusicAgentState) -> Dict[str, Any]:
    """Respond 节点 — 格式化最终回复，处理 help/clear/exit 等简单指令"""
    intent = state.get("intent", "respond")
    params = state.get("task_params", {})
    final_response = state.get("final_response", "")
    trace = state.get("agent_trace", []) + ["respond: formatting"]

    # 如果前置节点已生成回复，直接传递
    if final_response:
        return {"final_response": final_response, "agent_trace": trace}

    if intent == "help":
        return {"final_response": _help_text(), "agent_trace": trace}

    if intent == "clear":
        return {"final_response": "✅ 会话已清除。有什么可以帮你的？",
                "agent_trace": trace}

    if intent == "exit":
        return {"final_response": "再见！享受音乐！🎶",
                "agent_trace": trace}

    if intent == "cancel":
        return {"final_response": "✅ 已取消。有什么可以帮你的？",
                "agent_trace": trace}

    # 歌单相关
    if intent == "list_playlists":
        return {"final_response": "📋 播放列表保存在音乐库的 Playlists/ 目录下。\n"
                "创建歌单：说「创建一个运动时听的歌单」或「创建一个开心的歌单」。",
                "agent_trace": trace}
    if intent in ("playlist", "smart_playlist"):
        return {"final_response": '📋 创建智能歌单：告诉我场景（如「运动」）或情绪（如「开心」），'
                '我会从你的音乐库中自动筛选匹配的歌曲生成播放列表。',
                "agent_trace": trace}

    # 模型管理
    if intent == "list_models":
        from core.vector_store import EMBEDDING_MODELS
        return {"final_response": "📊 可用 Embedding 模型：\n" +
                "\n".join(f"  • {k}: {v}" for k, v in EMBEDDING_MODELS.items()),
                "agent_trace": trace}
    if intent == "switch_model":
        return {"final_response": "🔄 切换模型：输入「切换模型 <模型名>」来更换 embedding 模型。\n"
                "查看可用模型：输入「模型列表」。",
                "agent_trace": trace}
    if intent == "current_model":
        return {"final_response": "📊 查看当前模型：当前使用的 embedding 模型信息。\n"
                "输入「模型列表」查看所有可用模型。",
                "agent_trace": trace}

    # 元数据类
    if intent in ("detect_single_language", "analyze_single_emotion"):
        target = "语言" if intent == "detect_single_language" else "情绪"
        return {"final_response": f"🔍 单曲{target}检测：输入「检测 歌手 - 歌名 的{target}」。\n"
                "批量检测：输入「语言分布」或「分析情绪」。",
                "agent_trace": trace}

    # 导入导出
    if intent == "export_library":
        return {"final_response": "📤 导出音乐库：目前支持导出为 CSV 格式。\n"
                "包含歌曲名、艺术家、专辑、语言、情绪等字段。",
                "agent_trace": trace}
    if intent == "import_library":
        return {"final_response": "📥 导入音乐库：将 CSV 文件放入音乐库目录后执行「扫描」即可。",
                "agent_trace": trace}

    # 确认操作提示
    if state.get("requires_confirmation"):
        return {
            "final_response": state.get("final_response", "请确认此操作：回复'确认'执行，'取消'放弃。"),
            "agent_trace": trace,
        }

    # 最终兜底
    return {"final_response": "有什么可以帮你的？试试搜索歌曲、播放音乐或管理音乐库。输入「帮助」查看全部功能。",
            "agent_trace": trace}


def _help_text() -> str:
    return """🎵 Music Agent — 智能音乐助手

📡 搜索查询：
  • 直接说歌名/艺术家名搜索
  • "有哪些韩语歌" — 按语言筛选
  • "开心的歌" — 按情绪筛选
  • "推荐几首歌" — 随机推荐

🎧 播放：
  • "播放晴天" — 播放指定歌曲
  • "播放周杰伦的歌" — 播放指定歌手

📊 统计分析：
  • "语言分布" — 查看语言统计
  • "分析情绪" — 分析音乐库情绪分布

🔧 管理：
  • "扫描" — 更新音乐库
  • "整理" — 整理文件目录
  • "去重" — 清理重复文件

🌐 发现：
  • "发现新音乐" — 从外部源发现
  • "发现像陈奕迅的歌"

💡 输入 '退出' 结束对话"""
