# -*- coding: utf-8 -*-
"""Metadata Agent 节点 — 元数据修复与补全（含 human-in-the-loop）"""
from typing import Dict, Any
import json

from graph.state import MusicAgentState
from graph.kimi_adapter import KimiChatModel


def metadata_node(state: MusicAgentState) -> Dict[str, Any]:
    """Metadata Agent 节点 — 元数据诊断/修复/同步"""
    intent = state.get("intent", "")
    params = state.get("task_params", {})
    trace = state.get("agent_trace", []) + ["metadata: running"]

    # 诊断
    if intent == "diagnose":
        return _run_diagnose(trace)

    # 同步情绪缓存
    if intent == "sync_emotion":
        return _run_sync_emotion(trace)

    # 修复单首
    if intent == "fix_single":
        return _run_fix_single(params, trace)

    # 批量修复（需要确认）
    if intent in ("fix_metadata", "fix_metadata_issues"):
        if state.get("requires_confirmation") and state.get("pending_action"):
            return _execute_fix_metadata(params, trace)
        return _preview_fix_metadata(trace)

    return {"final_response": "元数据操作完成。", "agent_trace": trace}


def _collect_missing_metadata():
    """共用：扫描音乐库，返回 (stats, incomplete_list)"""
    from agents.librarian import get_librarian

    agent = get_librarian()
    stats = agent.get_stats()

    incomplete = []
    for song in agent.songs.values():
        issues = []
        if song.artist == "Unknown":
            issues.append("缺艺术家")
        if song.title == "Unknown" or not song.title:
            issues.append("缺标题")
        if not song.album or song.album == "Unknown":
            issues.append("缺专辑")
        if not LibrarianAgent.has_embedded_cover(song.file_path):
            issues.append("缺封面")
        if issues:
            incomplete.append({
                "file": song.file_path,
                "artist": song.artist,
                "title": song.title,
                "issues": issues,
            })
    return stats, incomplete


def _format_diagnose_report(stats: dict, incomplete: list) -> str:
    """将诊断数据格式化为报告文本"""
    from pathlib import Path
    response = f"""📊 元数据诊断报告

总歌曲: {stats['total_songs']} 首
艺术家: {stats['artists']} 位
流派: {stats['genres']} 种

⚠️ 元数据不完整: {len(incomplete)} 首"""

    if incomplete:
        response += "\n\n前 10 首需修复：\n"
        for item in incomplete[:10]:
            issues_str = "、".join(item["issues"])
            fname = Path(item["file"]).name if "file" in item else item.get("file", "")
            response += f"  • {fname}: {issues_str}\n"
        response += f"\n💡 输入「一键修复」开始修复（共 {len(incomplete)} 首）"

    return response


def _run_diagnose(trace: list) -> Dict[str, Any]:
    """诊断元数据完整性"""
    stats, incomplete = _collect_missing_metadata()
    response = _format_diagnose_report(stats, incomplete)
    return {"final_response": response, "agent_trace": trace + ["metadata: diagnose done"]}


def _preview_fix_metadata(trace: list) -> Dict[str, Any]:
    """先诊断，列出缺什么，再附确认提示"""
    stats, incomplete = _collect_missing_metadata()
    report = _format_diagnose_report(stats, incomplete)
    if incomplete:
        report += f"\n\n🔧 确认后将尝试修复以上 {len(incomplete)} 首歌曲的元数据。"
    else:
        report += "\n\n🎉 所有歌曲元数据完整，无需修复！"
        return {"final_response": report, "agent_trace": trace + ["metadata: all complete"]}
    report += "\n⚠️ 确认执行请回复'确认'，取消请回复'取消'。"
    return {
        "final_response": report,
        "requires_confirmation": True,
        "pending_action": {"action_type": "fix_metadata", "params": {}, "description": "批量修复元数据"},
        "agent_trace": trace + ["metadata: awaiting confirmation"],
    }


def _execute_fix_metadata(params: dict, trace: list) -> Dict[str, Any]:
    """执行元数据修复"""
    from agents.librarian import get_librarian

    agent = get_librarian()
    result = agent.run("fix_metadata", dry_run=False)
    return {
        "final_response": f"✅ 元数据修复完成！\n处理: {result.get('fixed', 0)} 首",
        "agent_trace": trace + ["metadata: fix done"],
    }


def _run_sync_emotion(trace: list) -> Dict[str, Any]:
    """同步情绪缓存到数据库"""
    try:
        from core.emotion_analyzer_simple import SimpleEmotionAnalyzer
        from core.music_library_db import get_library_db
        from pathlib import Path
        import json

        cache_file = Path("data/emotion_cache.json")
        if not cache_file.exists():
            return {"final_response": "暂无情绪缓存，请先运行「分析情绪」。",
                    "agent_trace": trace + ["metadata: no emotion cache"]}

        with open(cache_file, "r", encoding="utf-8") as f:
            cache = json.load(f)

        lib_db = get_library_db()
        synced = 0
        for key, data in cache.items():
            emotion = data.get("emotion")
            if emotion and data.get("artist") and data.get("title"):
                lib_db.update_emotion(data["artist"], data["title"], emotion)
                synced += 1

        return {"final_response": f"✅ 已同步 {synced} 首歌曲的情绪标签到数据库。",
                "agent_trace": trace + ["metadata: sync done"]}
    except Exception as e:
        return {"final_response": f"同步失败: {e}",
                "agent_trace": trace + [f"metadata: sync error {e}"]}


def _run_fix_single(params: dict, trace: list) -> Dict[str, Any]:
    """修复单首歌曲"""
    from agents.librarian import get_librarian
    from agents.metadata_enhancer import MetadataEnhancer

    file_hint = params.get("file", params.get("song_name", ""))
    agent = get_librarian()

    # 查找匹配
    matched = None
    for song in agent.songs.values():
        if file_hint.lower() in Path(song.file_path).name.lower():
            matched = song
            break

    if not matched:
        return {"final_response": f"未找到匹配 '{file_hint}' 的歌曲。",
                "agent_trace": trace + ["metadata: fix_single not found"]}

    enhancer = MetadataEnhancer(kimi_client=agent.kimi)
    metadata = enhancer.search_by_filename(Path(matched.file_path).name, download_cover=True)
    if metadata and metadata.get("title") and metadata.get("artist"):
        matched.artist = metadata["artist"]
        matched.title = metadata["title"]
        if metadata.get("album"):
            matched.album = metadata["album"]
        agent._write_metadata_to_file(matched, cover_path=metadata.get("cover_path"))
        return {"final_response": f"✅ 已修复: {metadata['artist']} - {metadata['title']}",
                "agent_trace": trace + ["metadata: fix_single done"]}

    return {"final_response": f"未能在线找到 '{file_hint}' 的元数据。",
            "agent_trace": trace + ["metadata: fix_single failed"]}
