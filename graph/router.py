# -*- coding: utf-8 -*-
"""条件边路由函数 — 根据意图分发到对应 Agent 节点"""


def route_by_intent(state) -> str:
    """根据意图返回下一个节点名称"""
    intent = state.get("intent", "respond")

    routing_map = {
        # Librarian 域
        "query": "librarian",
        "search": "librarian",
        "scan": "librarian",
        "play_by_name": "librarian",
        "play_by_artist": "librarian",
        "play_all": "librarian",
        "play": "librarian",
        "play_all_results": "librarian",
        "play_all_except": "librarian",
        "batch_select": "librarian",
        "playlist_from_results": "librarian",
        "query_emotion_songs": "librarian",
        "query_language_songs": "librarian",
        "recommend_random": "librarian",

        # Scout 域
        "discover": "scout",

        # Curator 域（scout 完成后自动流转）
        "curator": "curator",

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

        # 直接 respond 的简单指令
        "help": "respond",
        "clear": "respond",
        "exit": "respond",
        "cancel": "respond",
        "show_language_stats": "respond",
        "analyze_emotion": "respond",
        "show_library_stats": "respond",
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
        "download_lyrics": "respond",
        "generate_lyrics_whisper": "respond",
        "monitor": "respond",
    }

    return routing_map.get(intent, "respond")
