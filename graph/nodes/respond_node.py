# -*- coding: utf-8 -*-
"""Respond 节点 — 格式化最终回复并处理简单指令"""
from pathlib import Path
from typing import Dict, Any

from graph.state import MusicAgentState
from graph.utils import load_config
from core.folder_watcher import FolderWatcher

_watcher = None


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

    if intent == "scan":
        return _handle_scan(trace)

    # show_language_stats
    if intent == "show_language_stats":
        return _show_language_stats(state, trace)

    # analyze_emotion
    if intent == "analyze_emotion":
        return _show_emotion_stats(state, trace)

    # cancel — 取消待确认操作
    if intent == "cancel":
        return {"final_response": "✅ 已取消。有什么可以帮你的？",
                "agent_trace": trace}

    # monitor — 文件监控
    if intent == "monitor":
        return _handle_monitor(params, trace)

    # 库统计
    if intent == "show_library_stats":
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
            return {"final_response": "\n".join(lines), "agent_trace": trace}
        except Exception:
            return {"final_response": "📊 无法获取库统计，请先执行「扫描」。",
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
        return {"final_response": f"📊 可用 Embedding 模型：\n" +
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

    # 纠错类
    if intent in ("correct_language", "correct_emotion"):
        target = "语言" if intent == "correct_language" else "情绪"
        return {"final_response": f"✏️ 纠正{target}：说「标记 歌手 - 歌名 为 {target}标签」。\n"
                f"例如：「标记 周杰伦 - 晴天 为 国语」或「标记 周杰伦 - 晴天 为 怀旧」。",
                "agent_trace": trace}

    # 元数据类
    if intent == "update_song_info":
        return {"final_response": "✏️ 更新歌曲信息：说「更新 歌名 的 字段 为 值」。\n"
                "例如：「更新 晴天 的 语言 为 国语」或「更新 晴天 的 情绪 为 怀旧」。",
                "agent_trace": trace}
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

    # 格式转换
    if intent == "convert":
        return {"final_response": "🔄 音频格式转换：支持 FLAC/WAV/APE → MP3。\n"
                "将文件放入音乐库目录后，系统会自动检测并转换。",
                "agent_trace": trace}

    # 确认操作提示
    if state.get("requires_confirmation"):
        return {
            "final_response": state.get("final_response", "请确认此操作：回复'确认'执行，'取消'放弃。"),
            "agent_trace": trace,
        }

    # 最终兜底 — 不再调 LLM，避免胡编
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


def _show_language_stats(state: MusicAgentState, trace: list) -> Dict[str, Any]:
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
    return {"final_response": "\n".join(lines), "agent_trace": trace}


def _show_emotion_stats(state: MusicAgentState, trace: list) -> Dict[str, Any]:
    """情绪统计"""
    from core.emotion_analyzer_simple import SimpleEmotionAnalyzer
    from agents.librarian import get_librarian

    agent = get_librarian()
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





def _handle_scan(trace: list) -> Dict[str, Any]:
    """直接执行扫描，不经过 LLM"""
    try:
        from agents.librarian import get_librarian
        agent = get_librarian(config)
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
        return {"final_response": "\n".join(lines), "agent_trace": trace + ["respond: scan done"]}
    except Exception as e:
        return {"final_response": f"⚠️ 扫描失败: {e}",
                "agent_trace": trace + ["respond: scan failed"]}


def _handle_monitor(params: dict, trace: list) -> Dict[str, Any]:
    """启动/停止文件监控"""
    global _watcher
    action = params.get("action", "")

    if action == "stop":
        if _watcher is not None and _watcher.is_running:
            _watcher.stop()
            _watcher = None
            return {"final_response": "🔍 文件监控已停止。",
                    "agent_trace": trace + ["respond: monitor stopped"]}
        return {"final_response": "🔍 文件监控未在运行。",
                "agent_trace": trace + ["respond: monitor not running"]}

    if action == "start":
        if _watcher is not None and _watcher.is_running:
            dirs = _watcher._watch_dirs
            return {"final_response": f"🔍 文件监控已在运行中。\n监控目录: {', '.join(dirs)}",
                    "agent_trace": trace + ["respond: monitor already running"]}
        try:
            from agents.librarian import get_librarian
            config = load_config()
            library_path = config.get("library", {}).get("path", "")
            if not library_path:
                return {"final_response": "⚠️ 未配置音乐库路径，请检查 config.yaml。",
                        "agent_trace": trace + ["respond: monitor no path"]}

            watch_dirs = [
                str(Path(library_path) / "MUSIC"),
                str(Path(library_path) / "ALBUM"),
            ]
            # 只监控实际存在的目录
            existing = [d for d in watch_dirs if Path(d).exists() and Path(d).is_dir()]
            if not existing:
                return {"final_response": f"⚠️ 监控目录不存在:\n  {watch_dirs[0]}\n  {watch_dirs[1]}\n请确认音乐库路径配置正确。",
                        "agent_trace": trace + ["respond: monitor dirs not found"]}

            librarian = get_librarian(config)
            _watcher = FolderWatcher(watch_dirs=existing)
            _watcher.set_librarian(librarian)
            _watcher.start()
            return {"final_response": f"🔍 文件监控已启动。\n监控目录:\n  " + "\n  ".join(existing) +
                    "\n添加新歌曲到监控目录后会自动扫描入库。",
                    "agent_trace": trace + ["respond: monitor started"]}
        except Exception as e:
            return {"final_response": f"⚠️ 启动监控失败: {e}",
                    "agent_trace": trace + ["respond: monitor start failed"]}

    # 无 action — 返回当前状态
    if _watcher is not None and _watcher.is_running:
        dirs = _watcher._watch_dirs
        return {"final_response": f"🔍 文件监控运行中。\n监控目录:\n  " + "\n  ".join(dirs) +
                "\n输入「关闭监控」停止。",
                "agent_trace": trace + ["respond: monitor status"]}
    return {"final_response": "🔍 文件监控未启动。输入「开启监控」自动监听音乐库目录，「关闭监控」停止。",
            "agent_trace": trace + ["respond: monitor status"]}



