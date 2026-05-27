# -*- coding: utf-8 -*-
"""条件边路由函数 — 根据意图分发到对应 Agent 节点

[Phase 2] Hermes Gateway 已替代旧 intent_router 做意图识别，
此文件只负责 intent → node_name 的纯转发映射。
"""


def route_by_intent(state) -> str:
    """根据意图返回下一个节点名称。

    优先使用 Hermes Gateway 直接指定的 target_agent，
    否则用 intent 做映射。
    """
    target = state.get("target_agent", "")
    if target in {"librarian", "organizer", "metadata", "respond"}:
        return target

    intent = state.get("intent", "respond")

    # Librarian 域
    if intent in {
        "query", "search", "play_by_name", "play_by_artist",
        "play_all", "play_random", "play", "play_all_results",
        "play_all_except", "batch_select", "playlist_from_results",
        "query_emotion_songs", "query_language_songs",
        "recommend_random", "scan", "show_language_stats",
        "analyze_emotion", "clear_emotion_cache", "show_library_stats",
    }:
        return "librarian"

    # Organizer 域
    if intent in {"organize", "dedup", "analyze"}:
        return "organizer"

    # Metadata 域
    if intent in {
        "fix_metadata", "fix_single", "diagnose",
        "fix_metadata_issues", "sync_emotion",
        "correct_emotion", "correct_language", "update_song_info",
        "detect_single_language", "analyze_single_emotion",
    }:
        return "metadata"

    # Respond 域 — 所有其他
    return "respond"
