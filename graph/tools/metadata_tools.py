# -*- coding: utf-8 -*-
"""Metadata 工具集 — 元数据诊断、修复、标签纠正"""
import json
from pathlib import Path

from langchain_core.tools import tool

# 情绪标签映射
EMOTION_MAP = {
    '快乐': 'happy', '高兴': 'happy', '开心': 'happy', '欢快': 'happy',
    '悲伤': 'sad', '难过': 'sad', '伤感': 'sad', '忧郁': 'sad',
    '激情': 'energetic', '激烈': 'energetic', '热血': 'energetic',
    '平静': 'calm', '安静': 'calm', '舒缓': 'calm', '放松': 'calm',
    '浪漫': 'romantic', '温柔': 'romantic',
    '怀旧': 'nostalgic', '回忆': 'nostalgic',
    '愤怒': 'angry', '愤慨': 'angry',
    '专注': 'focus',
    '派对': 'party',
    'happy': 'happy', 'sad': 'sad', 'energetic': 'energetic',
    'calm': 'calm', 'romantic': 'romantic', 'nostalgic': 'nostalgic',
    'angry': 'angry', 'focus': 'focus', 'party': 'party',
}

EMOTION_DISPLAY = {
    'happy': '快乐', 'sad': '悲伤', 'energetic': '激情',
    'calm': '平静', 'romantic': '浪漫', 'nostalgic': '怀旧',
    'angry': '愤怒', 'focus': '专注', 'party': '派对',
}


def _find_song(song_hint: str):
    """在音乐库中按关键词查找歌曲，返回 Song 对象或 None。"""
    from agents.librarian import get_librarian

    agent = get_librarian()
    hint_lower = song_hint.lower()

    for song in agent.songs.values():
        combined = f"{song.artist} {song.title}".lower()
        if hint_lower in combined or any(w in combined for w in hint_lower.split()):
            return song

    # 降级：向量搜索
    results = agent.query(song_hint, top_k=1)
    if results:
        return results[0].get("song")
    return None


def _has_embedded_cover(file_path: str) -> bool:
    """检查音频文件是否内嵌封面。"""
    try:
        from mutagen import File as MutagenFile
        f = MutagenFile(file_path)
        if f and hasattr(f, 'tags'):
            return bool(f.tags and any(
                f.tags.getall(k) for k in f.tags.keys()
                if k.startswith('APIC') or k.startswith('PIC') or k == 'covr'
            ))
    except Exception:
        pass
    return False


# ── Tools ──────────────────────────────────────────────────

@tool
def diagnose_metadata() -> str:
    """诊断音乐库元数据完整性。检查每首歌是否缺艺术家、标题、专辑、封面。
    返回诊断报告（含不完整歌曲列表和统计摘要）。"""
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
        if not _has_embedded_cover(song.file_path):
            issues.append("缺封面")
        if issues:
            incomplete.append({
                "file": song.file_path,
                "artist": song.artist,
                "title": song.title,
                "issues": issues,
            })

    return json.dumps({
        "total_songs": stats.get("total_songs", 0),
        "artists": stats.get("artists", 0),
        "genres": stats.get("genres", 0),
        "incomplete_count": len(incomplete),
        "incomplete_samples": incomplete[:10],
    }, ensure_ascii=False, indent=2)


@tool
def fix_single_song(file_hint: str) -> str:
    """修复单首歌曲的元数据（在线搜索补全歌手名、标题、封面等）。
    file_hint 是歌曲文件名中的关键词，如 '晴天'、'Dynamite'。"""
    from agents.librarian import get_librarian
    from agents.metadata_enhancer import MetadataEnhancer

    agent = get_librarian()
    matched = None
    for song in agent.songs.values():
        if file_hint.lower() in Path(song.file_path).name.lower():
            matched = song
            break

    if not matched:
        return json.dumps({"error": f"未找到匹配 '{file_hint}' 的歌曲"}, ensure_ascii=False)

    enhancer = MetadataEnhancer(kimi_client=agent.kimi)
    metadata = enhancer.search_by_filename(Path(matched.file_path).name, download_cover=True)
    if metadata and metadata.get("title") and metadata.get("artist"):
        matched.artist = metadata["artist"]
        matched.title = metadata["title"]
        if metadata.get("album"):
            matched.album = metadata["album"]
        agent._write_metadata_to_file(matched, cover_path=metadata.get("cover_path"))
        return json.dumps({
            "status": "fixed",
            "artist": metadata["artist"],
            "title": metadata["title"],
            "album": metadata.get("album", ""),
        }, ensure_ascii=False)

    return json.dumps({"error": f"未能在线找到 '{file_hint}' 的元数据"}, ensure_ascii=False)


@tool
def fix_metadata_batch(dry_run: bool = True) -> str:
    """批量修复音乐库元数据。dry_run=True 仅预览不执行，dry_run=False 实际修复。
    首次调用必须 dry_run=True 让用户确认范围和影响。"""
    from agents.librarian import get_librarian

    _, incomplete = _collect_incomplete()
    if not incomplete:
        return json.dumps({"message": "所有歌曲元数据完整，无需修复。"}, ensure_ascii=False)

    if dry_run:
        return json.dumps({
            "mode": "preview",
            "incomplete_count": len(incomplete),
            "samples": incomplete[:10],
            "message": f"预览模式：共 {len(incomplete)} 首需要修复。设置 dry_run=False 执行。",
        }, ensure_ascii=False)

    agent = get_librarian()
    result = agent.run("fix_metadata", dry_run=False)
    return json.dumps({
        "mode": "executed",
        "fixed": result.get("fixed", 0),
        "processed": result.get("processed", 0),
    }, ensure_ascii=False)


def _collect_incomplete():
    """内部辅助：收集元数据不完整的歌曲列表。"""
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
        if not _has_embedded_cover(song.file_path):
            issues.append("缺封面")
        if issues:
            incomplete.append({
                "file": song.file_path,
                "artist": song.artist,
                "title": song.title,
                "issues": issues,
            })
    return stats, incomplete


@tool
def sync_emotion_cache() -> str:
    """同步情绪缓存到数据库。将 data/emotion_cache.json 中的情绪结果写入 SQLite。"""
    import json as _json

    cache_file = Path("data/emotion_cache.json")
    if not cache_file.exists():
        return json.dumps({"error": "暂无情绪缓存，请先运行情绪分析。"}, ensure_ascii=False)

    with open(cache_file, "r", encoding="utf-8") as f:
        cache = _json.load(f)

    from core.music_library_db import get_library_db
    lib_db = get_library_db()
    synced = 0
    for key, data in cache.items():
        emotion = data.get("emotion")
        if emotion and data.get("artist") and data.get("title"):
            lib_db.update_emotion(data["artist"], data["title"], emotion)
            synced += 1

    return json.dumps({"synced": synced}, ensure_ascii=False)


@tool
def update_song_tag(song_hint: str, field: str, value: str) -> str:
    """更新单首歌曲的语言或情绪标签。field='emotion' 或 'language'。
    情绪值用中文（快乐/悲伤/激情/平静/浪漫/怀旧/愤怒/专注/派对）或英文。
    例如：update_song_tag(song_hint='晴天', field='emotion', value='快乐')"""
    from core.music_library_db import get_library_db

    matched = _find_song(song_hint)
    if not matched:
        return json.dumps({"error": f"未找到匹配「{song_hint}」的歌曲"}, ensure_ascii=False)

    lib_db = get_library_db()

    if field == "emotion":
        emotion_en = EMOTION_MAP.get(value.strip())
        if not emotion_en:
            valid = "、".join(EMOTION_DISPLAY.values())
            return json.dumps({"error": f"不支持的情绪标签。可用：{valid}"}, ensure_ascii=False)
        lib_db.update_emotion(matched.artist, matched.title, emotion_en, "manual")
        display = EMOTION_DISPLAY.get(emotion_en, emotion_en)
        return json.dumps({
            "status": "updated",
            "artist": matched.artist,
            "title": matched.title,
            "field": "emotion",
            "new_value": display,
        }, ensure_ascii=False)

    if field == "language":
        lib_db.update_language(matched.artist, matched.title, value.strip(), "manual")
        return json.dumps({
            "status": "updated",
            "artist": matched.artist,
            "title": matched.title,
            "field": "language",
            "new_value": value.strip(),
        }, ensure_ascii=False)

    return json.dumps({"error": f"不支持的字段 '{field}'，只支持 emotion 和 language。"}, ensure_ascii=False)


# ── 工具集 ─────────────────────────────────────────────────

METADATA_TOOLS = [
    diagnose_metadata,
    fix_single_song,
    fix_metadata_batch,
    sync_emotion_cache,
    update_song_tag,
]
