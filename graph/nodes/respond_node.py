# -*- coding: utf-8 -*-
"""Respond 节点 — 格式化最终回复并处理简单指令"""
from typing import Dict, Any

from graph.state import MusicAgentState


def _msg_content(msg) -> str:
    """从 dict 或 LangChain BaseMessage 中安全提取文本内容。"""
    if isinstance(msg, dict):
        return msg.get("content", "") or ""
    return getattr(msg, "content", "") or ""


def respond_node(state: MusicAgentState) -> Dict[str, Any]:
    """Respond 节点 — 格式化最终回复，处理 help/clear/exit 等简单指令"""
    intent = state.get("intent", "respond")
    params = state.get("task_params", {})
    messages = state.get("messages", [])
    final_response = state.get("final_response", "")
    trace = state.get("agent_trace", []) + ["respond: formatting"]

    # 如果前置节点已生成回复，直接传递
    if final_response:
        return {"final_response": final_response, "agent_trace": trace}

    # 处理简单指令
    if intent == "help":
        return {"final_response": _help_text(), "agent_trace": trace}

    if intent == "clear":
        return {"final_response": "✅ 会话已清除。有什么可以帮你的？",
                "agent_trace": trace}

    if intent == "exit":
        return {"final_response": "再见！享受音乐！🎶",
                "agent_trace": trace}

    # show_language_stats
    if intent == "show_language_stats":
        return _show_language_stats(state, trace)

    # analyze_emotion
    if intent == "analyze_emotion":
        return _show_emotion_stats(state, trace)

    # play / play_by_name / play_by_artist / play_all
    if intent in ("play", "play_by_name", "play_by_artist", "play_all"):
        return _handle_play(intent, params, trace)

    # 默认：如果有待确认操作
    if state.get("requires_confirmation"):
        return {
            "final_response": state.get("final_response", "请确认此操作：回复'确认'执行，'取消'放弃。"),
            "agent_trace": trace,
        }

    # 兜底：用 LLM 生成通用回复
    user_input = ""
    if messages:
        user_input = _msg_content(messages[-1])

    if not user_input:
        return {"final_response": "有什么可以帮你的？试试搜索歌曲、发现新音乐或整理音乐库。",
                "agent_trace": trace}

    try:
        from graph.kimi_adapter import KimiChatModel
        llm = KimiChatModel(model="moonshot-v1-8k", temperature=0.7, max_tokens=500)
        response = llm.invoke(f"用户说：{user_input}\n请用中文友好回复，20字以内。")
        reply = response.content if hasattr(response, 'content') else str(response)
        return {"final_response": reply, "agent_trace": trace}
    except Exception:
        return {"final_response": _default_reply(user_input), "agent_trace": trace}


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


def _show_language_stats(state: MusicAgentState, trace: list) -> Dict[str, Any]:
    """语言统计"""
    from core.language_detector import detector
    from agents.librarian import LibrarianAgent
    import yaml
    from pathlib import Path

    config_path = Path(__file__).resolve().parent.parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    agent = LibrarianAgent(config)
    for song in agent.songs.values():
        detector.detect(song.title, song.artist, song.file_path)

    stats = detector.get_stats()
    total = sum(stats.values())

    lines = ["📊 歌曲语言分布统计", "=" * 40]
    for lang, count in stats.items():
        bar = "█" * (count * 30 // total if total > 0 else 0)
        lines.append(f"  {lang:6} | {bar:30} | {count}首")
    lines.append("=" * 40)
    lines.append(f"总计: {total} 首")
    lines.append("\n💡 输入「有哪些韩语歌」查询特定语言歌曲")

    return {"final_response": "\n".join(lines), "agent_trace": trace}


def _show_emotion_stats(state: MusicAgentState, trace: list) -> Dict[str, Any]:
    """情绪统计"""
    from core.emotion_analyzer_simple import SimpleEmotionAnalyzer
    from agents.librarian import LibrarianAgent
    import yaml
    from pathlib import Path

    config_path = Path(__file__).resolve().parent.parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    agent = LibrarianAgent(config)
    analyzer = SimpleEmotionAnalyzer()

    emotion_stats = {}
    for song in agent.songs.values():
        cache_key = analyzer._get_file_hash(song.file_path)
        if cache_key in analyzer._cache:
            emotion = analyzer._cache[cache_key].get("emotion", "unknown")
            emotion_stats[emotion] = emotion_stats.get(emotion, 0) + 1

    if not emotion_stats:
        return {"final_response": "暂无情分析结果。输入「分析情绪」来为音乐库标注情绪。",
                "agent_trace": trace}

    emotion_names = {
        'happy': '快乐', 'sad': '悲伤', 'energetic': '激情',
        'calm': '平静', 'romantic': '浪漫', 'nostalgic': '怀旧',
        'angry': '愤怒', 'focus': '专注', 'party': '派对',
    }
    total = sum(emotion_stats.values())
    lines = ["🎭 歌曲情绪分布统计", "=" * 40]
    for emotion, count in sorted(emotion_stats.items(), key=lambda x: -x[1]):
        name = emotion_names.get(emotion, emotion)
        bar = "█" * (count * 30 // total if total > 0 else 0)
        lines.append(f"  {name:6} | {bar:30} | {count}首")
    lines.append("=" * 40)
    lines.append(f"总计: {total} 首")

    return {"final_response": "\n".join(lines), "agent_trace": trace}


def _handle_play(intent: str, params: dict, trace: list) -> Dict[str, Any]:
    """播放指令 — 所有播放请求现在由 librarian 节点的 react agent 处理。
    此函数仅在播放请求无法路由到 librarian 时作为兜底。"""
    song_hint = params.get("song_name") or params.get("artist") or params.get("title_hint") or ""
    if song_hint:
        return {"final_response": f"🎵 正在尝试播放: {song_hint}\n请确保 foobar2000 已安装。",
                "agent_trace": trace}
    return {"final_response": "🎵 播放功能需要指定歌曲名或歌手。试试「播放晴天」或「播放周杰伦的歌」。",
            "agent_trace": trace}


def _default_reply(user_input: str) -> str:
    """默认回复"""
    if any(w in user_input for w in ["你好", "嗨", "hello", "hi", "在吗"]):
        return "你好！我是你的音乐助手。想听什么歌，或者需要管理音乐库吗？"
    return f"收到！你可以试试：搜索歌曲、查看语言分布、分析情绪、发现新音乐。输入「帮助」看更多。"
