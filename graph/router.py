# -*- coding: utf-8 -*-
"""条件边路由函数 — 根据意图分发到对应 Agent 节点"""


def route_by_intent(state) -> str:
    """根据意图返回下一个节点名称"""
    intent = state.get("intent", "respond")

    routing_map = {
        # Librarian 域
        "query": "librarian",
        "search": "librarian",
        "play_by_name": "librarian",
        "play_by_artist": "librarian",
        "play_all": "librarian",
        "play_random": "librarian",
        "play": "librarian",
        "play_all_results": "librarian",
        "play_all_except": "librarian",
        "batch_select": "librarian",
        "playlist_from_results": "librarian",
        "query_emotion_songs": "librarian",
        "query_language_songs": "librarian",
        "recommend_random": "librarian",

        # Organizer 域
        "organize": "organizer",
        "dedup": "organizer",
        "analyze": "organizer",

        # Metadata 域
        "fix_metadata": "metadata",
        "fix_single": "metadata",
        "diagnose": "metadata",
        "fix_metadata_issues": "metadata",
        "sync_emotion": "metadata",
        "correct_emotion": "metadata",
        "correct_language": "metadata",
        "update_song_info": "metadata",

        # scan/stats/emotion 归 librarian
        "scan": "librarian",
        "show_language_stats": "librarian",
        "analyze_emotion": "librarian",
        "clear_emotion_cache": "librarian",
        "show_library_stats": "librarian",

        # 直接 respond 的简单指令（纯文本，无业务逻辑）
        "help": "respond",
        "clear": "respond",
        "exit": "respond",
        "cancel": "respond",
        "list_playlists": "respond",
        "list_models": "respond",
        "switch_model": "respond",
        "current_model": "respond",
        "correct_language": "respond",
        "correct_emotion": "respond",
        "update_song_info": "respond",
        "detect_single_language": "respond",
        "analyze_single_emotion": "respond",
        "playlist": "respond",
        "smart_playlist": "respond",
        "export_library": "respond",
        "import_library": "respond",
        "convert": "respond",
    }

    return routing_map.get(intent, "respond")
