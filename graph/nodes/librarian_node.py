# -*- coding: utf-8 -*-
"""Librarian Agent 节点 — 音乐库管理与搜索"""
import json
from typing import Dict, Any

from langgraph.prebuilt import create_react_agent

from graph.state import MusicAgentState
from graph.kimi_adapter import KimiChatModel
from graph.tools.library_tools import LIBRARIAN_TOOLS
from graph.utils import msg_content


LIBRARIAN_SYSTEM_PROMPT = """你是音乐图书管理员，负责管理用户的本地音乐库。你的职责：

1. **搜索歌曲**：用 search_music 工具语义搜索音乐库，理解自然语言查询（如"周杰伦的歌"、"90年代摇滚"）
2. **扫描库**：用 scan_library 工具扫描音乐目录，发现新文件
3. **查询详情**：用 get_song_info 获取特定歌曲的完整元数据
4. **库统计**：用 get_library_stats 获取整体统计
5. **播放歌曲**：用 play_song 工具播放指定歌名
6. **播放全部**：用 play_all_songs 工具播放整个音乐库
7. **播放歌手**：用 play_by_artist 工具播放某个歌手的所有歌曲
8. **播放语言**：用 play_by_language 工具播放指定语言的所有歌曲
9. **播放情绪**：用 play_by_emotion 工具播放指定情绪的所有歌曲
10. **随机播放**：用 play_random 工具随机播放指定条件（数量+情绪+语言）的歌曲
   - "随机播放五首悲伤的中文歌" → play_random(count=5, emotion="sad", language="国语")
   - "随机播放十首开心的歌" → play_random(count=10, emotion="happy")

当用户要播放歌曲时，选择合适的播放工具：
- "播放晴天" → play_song
- "播放所有歌曲" / "播放全部" → play_all_songs
- "播放周杰伦的歌" → play_by_artist
- "播放所有英文歌" / "播放英语歌" → play_by_language(language="英语")
- "播放开心的歌" / "播放安静的歌曲" → play_by_emotion(emotion="happy"/"calm")
- "播放" + 具体歌名 → play_song

以中文回复用户，保持简洁友好。"""

_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        from graph.utils import load_config
        model = load_config().get("llm", {}).get("model", "moonshot-v1-8k")
        llm = KimiChatModel(model=model, temperature=0.3, max_tokens=800)
        _agent = create_react_agent(
            model=llm,
            tools=LIBRARIAN_TOOLS,
            prompt=LIBRARIAN_SYSTEM_PROMPT,
        )
    return _agent


def _extract_query_results(messages: list) -> list:
    """从 react agent 的 ToolMessage 中提取查询结果，写回 query_results"""
    results = []
    search_tools = {"search_music", "get_song_info"}
    for msg in messages:
        name = getattr(msg, "name", "") or ""
        if name in search_tools:
            try:
                data = json.loads(msg.content)
                if isinstance(data, list):
                    results.extend(data)
            except (json.JSONDecodeError, TypeError):
                pass
        elif name == "play_song":
            try:
                data = json.loads(msg.content)
                if data.get("status") == "multiple" and data.get("matches"):
                    results.extend(data["matches"])
            except (json.JSONDecodeError, TypeError):
                pass
    return results


def librarian_node(state: MusicAgentState) -> Dict[str, Any]:
    """Librarian Agent 节点入口"""
    intent = state.get("intent", "query")
    params = state.get("task_params", {})
    messages = state.get("messages", [])
    trace = state.get("agent_trace", [])

    # 管理类意图：直接处理，不走 react agent
    if intent == "scan":
        return _handle_scan(trace)

    if intent == "show_language_stats":
        return _handle_language_stats(trace)

    if intent == "analyze_emotion":
        return _handle_emotion_stats(state, trace)

    if intent == "clear_emotion_cache":
        return _handle_clear_emotion_cache(trace)

    if intent == "show_library_stats":
        return _handle_library_stats(trace)

    if not messages:
        return {
            "final_response": "请告诉我你想做什么。",
            "agent_trace": trace + ["librarian: no input"],
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

    if not assistant_reply:
        assistant_reply = "搜索完成，请在结果中查看。"

    query_results = _extract_query_results(final_msgs)

    return {
        "final_response": assistant_reply,
        "query_results": query_results,
        "agent_trace": trace + ["librarian: done"],
    }


def _handle_scan(trace: list) -> Dict[str, Any]:
    try:
        from agents.librarian import get_librarian
        agent = get_librarian()
        result = agent.scan_library()
        total = result.get("total_files", 0)
        new_songs = result.get("new_songs", 0)
        indexed = result.get("total_indexed", 0)
        lines = [
            "🔍 扫描完成！",
            "=" * 30,
            f"  扫描文件: {total} 个",
            f"  新增歌曲: {new_songs} 首",
            f"  已索引总数: {indexed} 首",
        ]
        return {"final_response": "\n".join(lines), "agent_trace": trace + ["librarian: scan done"]}
    except Exception as e:
        return {"final_response": f"⚠️ 扫描失败: {e}", "agent_trace": trace + ["librarian: scan failed"]}


def _handle_language_stats(trace: list) -> Dict[str, Any]:
    from core.music_library_db import get_library_db
    lib_db = get_library_db()
    records = lib_db.list_all()
    stats = {}
    for rec in records:
        lang = rec.language or "未知"
        stats[lang] = stats.get(lang, 0) + 1
    total = sum(stats.values())
    lines = ["📊 歌曲语言分布统计", "=" * 40]
    for lang, count in sorted(stats.items(), key=lambda x: -x[1]):
        bar = "█" * (count * 30 // total if total > 0 else 0)
        lines.append(f"  {lang:6} | {bar:30} | {count}首")
    lines.append("=" * 40)
    lines.append(f"总计: {total} 首")
    return {"final_response": "\n".join(lines), "agent_trace": trace + ["librarian: language_stats done"]}


def _handle_emotion_stats(state: MusicAgentState, trace: list) -> Dict[str, Any]:
    from core.emotion_analyzer_simple import SimpleEmotionAnalyzer
    from agents.librarian import get_librarian
    from core.kimi_client import KimiClient
    from graph.utils import load_config

    agent = get_librarian()
    kimi = None
    try:
        kimi = KimiClient(config=load_config())
    except Exception:
        pass
    analyzer = SimpleEmotionAnalyzer(kimi_client=kimi)

    songs = list(agent.songs.values())
    has_cache = any(
        analyzer._get_file_hash(s.file_path) in analyzer._cache
        for s in songs
        if s.file_path
    )
    force = state.get("task_params", {}).get("force", False)
    if not has_cache or force:
        songs_to_analyze = [
            {"file_path": s.file_path, "title": s.title, "artist": s.artist, "lyrics": None}
            for s in songs
        ]
        analyzer.batch_analyze(songs_to_analyze, verbose=False)

    emotion_stats = {}
    for song in songs:
        cache_key = analyzer._get_file_hash(song.file_path)
        if cache_key in analyzer._cache:
            emotion = analyzer._cache[cache_key].get("emotion", "unknown")
            emotion_stats[emotion] = emotion_stats.get(emotion, 0) + 1

    if not emotion_stats:
        return {"final_response": "暂无情绪分析结果。", "agent_trace": trace + ["librarian: emotion_stats empty"]}

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
    return {"final_response": "\n".join(lines), "agent_trace": trace + ["librarian: emotion_stats done"]}


def _handle_clear_emotion_cache(trace: list) -> Dict[str, Any]:
    from pathlib import Path as _P
    cache = _P("data/emotion_cache.json")
    if cache.exists():
        cache.unlink()
        return {"final_response": "✅ 情绪缓存已清除。下次分析情绪时会重新调用 Kimi 分析。",
                "agent_trace": trace + ["librarian: clear_emotion_cache done"]}
    return {"final_response": "📭 没有情绪缓存需要清除。",
            "agent_trace": trace + ["librarian: clear_emotion_cache noop"]}


def _handle_library_stats(trace: list) -> Dict[str, Any]:
    try:
        from agents.librarian import get_librarian
        agent = get_librarian()
        stats = agent.get_stats()
        lines = [
            "📊 音乐库统计",
            "=" * 30,
            f"  总歌曲数: {stats.get('total_songs', 0)}",
            f"  总艺术家: {stats.get('total_artists', 0)}",
            f"  总流派数: {stats.get('total_genres', 0)}",
        ]
        return {"final_response": "\n".join(lines), "agent_trace": trace + ["librarian: library_stats done"]}
    except Exception:
        return {"final_response": "📊 无法获取库统计，请先执行「扫描」。",
                "agent_trace": trace + ["librarian: library_stats failed"]}
