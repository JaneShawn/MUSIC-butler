# -*- coding: utf-8 -*-
"""Librarian 工具集 — 包装 core/ 和 agents/librarian.py 的功能"""
import json
import os
import random
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool
from core.vector_store import VectorStore
from core.music_library_db import get_library_db


@tool
def search_music(query: str, top_k: int = 10) -> str:
    """语义搜索本地音乐库。query 是自然语言查询（如'周杰伦的歌'、'90年代摇滚'）。
    返回匹配的歌曲列表（JSON格式，含歌曲名、艺术家、专辑）。"""
    from agents.librarian import get_librarian
    agent = get_librarian()
    results = agent.query(query, top_k=top_k)
    formatted = []
    for r in results:
        song = r.get("song")
        if song:
            formatted.append({
                "title": song.title,
                "artist": song.artist,
                "file_path": song.file_path,
            })
    return json.dumps(formatted, ensure_ascii=False, indent=2)


@tool
def scan_library() -> str:
    """扫描音乐库目录，发现新添加的音乐文件并入库。
    返回扫描结果：总文件数、新歌曲数、已索引总数（JSON格式）。"""
    from agents.librarian import get_librarian
    agent = get_librarian()
    result = agent.scan_library()
    return json.dumps(result, ensure_ascii=False)


@tool
def get_song_info(title_hint: str) -> str:
    """根据歌曲名或艺术家查询歌曲详情（从本地音乐库）。
    title_hint 是歌名或艺术家名的关键词，匹配成功后返回完整元数据（JSON格式）。"""
    from agents.librarian import get_librarian
    agent = get_librarian()
    results = agent.query(title_hint, top_k=5)
    formatted = []
    for r in results:
        song = r.get("song")
        if song:
            formatted.append({
                "title": song.title,
                "artist": song.artist,
                "file_path": song.file_path,
            })
    return json.dumps(formatted, ensure_ascii=False, indent=2)


@tool
def get_library_stats() -> str:
    """获取音乐库整体统计：总歌曲数、艺术家数、流派数、Top艺术家/流派（JSON格式）。"""
    from agents.librarian import get_librarian
    agent = get_librarian()
    stats = agent.get_stats()
    return json.dumps(stats, ensure_ascii=False)


# ═══════════════════════════════════════════
# 播放辅助函数（从旧 handler mixin 提取，改为独立函数）
# ═══════════════════════════════════════════

def _clean_play_name(name: str) -> str:
    """清洗歌名：去除书名号、歌手名后缀/前缀、通用后缀如'的歌'"""
    name = name.strip()
    if name.startswith("《") and name.endswith("》"):
        name = name[1:-1]
    name = re.sub(r'\s*[-–—]\s*\S+\s*$', '', name)
    name = re.sub(r'^\S+\s*[-–—]\s*', '', name)
    for suffix in ["的歌曲", "这首歌", "的歌"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break
    return name.strip()


def _create_m3u8_playlist(songs, playlist_name: str, config) -> Path:
    """创建 M3U8 播放列表文件。

    M3U8 中的路径相对于 M3U8 文件所在目录，确保 foobar2000 能正确解析。
    """
    import os
    library_path = config.get("library", {}).get("path", ".")
    playlist_dir = Path(library_path) / "Playlists"
    playlist_dir.mkdir(parents=True, exist_ok=True)

    playlist_path = playlist_dir / f"{playlist_name}.m3u8"
    lines = ["#EXTM3U", f"#PLAYLIST:{playlist_name}"]
    for song in songs:
        try:
            rel_path = os.path.relpath(song.file_path, str(playlist_dir))
            rel_path = rel_path.replace(os.sep, '/')
        except ValueError:
            rel_path = song.file_path
        duration = int(getattr(song, 'duration', 240) or 240)
        lines.append(f"#EXTINF:{duration},{song.artist} - {song.title}")
        lines.append(rel_path)

    playlist_path.write_text("\n".join(lines), encoding='utf-8')
    return playlist_path


def _play_with_foobar2000(file_path: str) -> Optional[str]:
    """调用 foobar2000 播放指定文件，返回状态字符串或 None。"""
    foobar_paths = [
        r"C:\Program Files\foobar2000\foobar2000.exe",
        r"C:\Program Files (x86)\foobar2000\foobar2000.exe",
        shutil.which("foobar2000"),
    ]
    foobar_exe = None
    for path in foobar_paths:
        if path and os.path.exists(path):
            foobar_exe = path
            break
    if not foobar_exe:
        return None
    try:
        subprocess.Popen(
            [foobar_exe, "/immediate", file_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        return "📱 已通过 foobar2000 播放"
    except Exception as e:
        return f"⚠️ 调用播放器失败: {e}"


# ═══════════════════════════════════════════
# 播放工具
# ═══════════════════════════════════════════

@tool
def play_song(title_hint: str) -> str:
    """通过歌名或歌手+歌名关键词播放一首歌曲。
    先搜索匹配，然后调用 foobar2000 播放。title_hint 为歌名关键词。
    返回播放结果描述（JSON格式）。"""
    from agents.librarian import get_librarian
    agent = get_librarian()

    if not agent.songs:
        agent.scan_library()

    song_name = _clean_play_name(title_hint)

    # L1: 精确子串匹配
    matched_songs = []
    for song in agent.songs.values():
        if song_name.lower() in song.title.lower() or \
           song_name.lower() in f"{song.artist} - {song.title}".lower():
            matched_songs.append(song)

    # L2: 模糊匹配
    if not matched_songs and len(song_name) >= 2:
        from difflib import SequenceMatcher
        best_matches = []
        for song in agent.songs.values():
            title_sim = SequenceMatcher(None, song_name.lower(), song.title.lower()).ratio()
            full_sim = SequenceMatcher(None, song_name.lower(),
                                       f"{song.artist} {song.title}".lower()).ratio()
            max_sim = max(title_sim, full_sim)
            if max_sim >= 0.6:
                best_matches.append((max_sim, song))
        if best_matches:
            best_matches.sort(key=lambda x: x[0], reverse=True)
            matched_songs = [s for _, s in best_matches[:5]]

    # L3: 降级 — 搜索库
    if not matched_songs:
        results = agent.query(title_hint, top_k=5)
        if results:
            formatted = []
            for i, r in enumerate(results, 1):
                s = r.get("song")
                if s:
                    formatted.append({
                        "index": i, "title": s.title, "artist": s.artist,
                        "album": s.album, "file_path": s.file_path,
                    })
            return json.dumps({"status": "multiple", "matches": formatted,
                               "message": f"找到 {len(formatted)} 首相关歌曲，请选择序号"},
                              ensure_ascii=False, indent=2)
        return json.dumps({"status": "not_found", "message": f"未找到包含 '{title_hint}' 的歌曲"},
                          ensure_ascii=False)

    # 单首直接播放
    if len(matched_songs) == 1:
        song = matched_songs[0]
        foobar_result = _play_with_foobar2000(song.file_path)
        if foobar_result:
            return json.dumps({
                "status": "playing",
                "title": song.title, "artist": song.artist,
                "file_path": song.file_path,
                "message": f"🎵 正在播放: {song.artist} - {song.title}",
                "foobar": foobar_result,
            }, ensure_ascii=False)
        return json.dumps({
            "status": "playlist_only",
            "title": song.title, "artist": song.artist,
            "file_path": song.file_path,
            "message": f"🎵 {song.artist} - {song.title}\n文件: {song.file_path}\n💡 未找到 foobar2000，请手动播放",
        }, ensure_ascii=False)

    # 多首候选 → 返回列表
    formatted = []
    for i, s in enumerate(matched_songs[:10], 1):
        formatted.append({
            "index": i, "title": s.title, "artist": s.artist,
            "album": s.album, "file_path": s.file_path,
        })
    return json.dumps({
        "status": "multiple",
        "matches": formatted,
        "message": f"找到 {len(matched_songs)} 首相关歌曲，请输入序号播放",
    }, ensure_ascii=False, indent=2)


@tool
def play_all_songs() -> str:
    """播放音乐库中的全部歌曲。创建 M3U8 播放列表并通过 foobar2000 播放。
    返回播放结果描述（JSON格式）。"""
    from agents.librarian import get_librarian
    agent = get_librarian()

    if not agent.songs:
        agent.scan_library()

    songs = list(agent.songs.values())
    if not songs:
        return json.dumps({"status": "empty", "message": "音乐库为空"}, ensure_ascii=False)

    from graph.utils import load_config
    config = load_config()
    playlist_name = f"全部歌曲_{len(songs)}首"
    playlist_path = _create_m3u8_playlist(songs, playlist_name, config)
    foobar_result = _play_with_foobar2000(str(playlist_path))

    return json.dumps({
        "status": "playing" if foobar_result else "playlist_only",
        "total": len(songs),
        "playlist": str(playlist_path),
        "playlist_name": playlist_name,
        "foobar": foobar_result,
        "message": (f"🎵 正在播放全部 {len(songs)} 首歌！\n📋 {playlist_name}"
                    if foobar_result else
                    f"✅ 全部歌曲播放列表已创建！\n🎵 {len(songs)} 首歌曲\n💾 {playlist_path}"),
    }, ensure_ascii=False)


@tool
def play_by_artist(artist: str) -> str:
    """播放指定歌手的所有歌曲。artist 为艺术家名。
    返回播放结果描述（JSON格式）。"""
    from agents.librarian import get_librarian
    agent = get_librarian()

    if not agent.songs:
        agent.scan_library()

    results = agent._filter_by_artist({"artist": artist}, top_k=1000)
    if not results:
        return json.dumps({"status": "not_found",
                           "message": f"未找到 {artist} 的歌曲"},
                          ensure_ascii=False)

    songs = [r["song"] for r in results]
    from graph.utils import load_config
    config = load_config()
    playlist_name = f"{artist}_全集_{len(songs)}首"
    playlist_path = _create_m3u8_playlist(songs, playlist_name, config)
    foobar_result = _play_with_foobar2000(str(playlist_path))

    return json.dumps({
        "status": "playing" if foobar_result else "playlist_only",
        "artist": artist,
        "total": len(songs),
        "playlist": str(playlist_path),
        "playlist_name": playlist_name,
        "foobar": foobar_result,
        "message": (f"🎵 正在播放 {artist} 的全部 {len(songs)} 首歌！\n📋 {playlist_name}"
                    if foobar_result else
                    f"✅ {artist} 播放列表已创建！\n🎵 {len(songs)} 首歌曲\n💾 {playlist_path}"),
    }, ensure_ascii=False)


@tool
def play_by_language(language: str) -> str:
    """播放指定语言的所有歌曲（如"播放所有英文歌"、"播放韩语歌"）。
    language 为语言名称（如'英语'、'韩语'、'日语'、'粤语'、'国语'）。
    创建 M3U8 播放列表并通过 foobar2000 播放，返回播放结果（JSON格式）。"""
    from agents.librarian import get_librarian
    agent = get_librarian()

    if not agent.songs:
        agent.scan_library()

    from core.language_detector import detector

    matched_objects = []
    for song in agent.songs.values():
        lang, source, conf = detector.detect(song.title, song.artist, song.file_path)
        if lang == language:
            matched_objects.append(song)

    if not matched_objects:
        return json.dumps({"status": "not_found",
                           "message": f"未找到「{language}」歌曲"},
                          ensure_ascii=False)

    from graph.utils import load_config
    config = load_config()
    playlist_name = f"{language}_全集_{len(matched_objects)}首"
    playlist_path = _create_m3u8_playlist(matched_objects, playlist_name, config)
    foobar_result = _play_with_foobar2000(str(playlist_path))

    return json.dumps({
        "status": "playing" if foobar_result else "playlist_only",
        "language": language,
        "total": len(matched_objects),
        "playlist": str(playlist_path),
        "playlist_name": playlist_name,
        "foobar": foobar_result,
        "message": (f"🎵 正在播放全部 {len(matched_objects)} 首「{language}」歌曲！\n📋 {playlist_name}"
                    if foobar_result else
                    f"✅ {language} 播放列表已创建！\n🎵 {len(matched_objects)} 首歌曲\n💾 {playlist_path}"),
    }, ensure_ascii=False)


@tool
def play_by_emotion(emotion: str) -> str:
    """播放指定情绪的所有歌曲（如"播放开心的歌"、"播放安静的歌曲"）。
    emotion 为情绪英文名（happy/sad/energetic/calm/romantic/nostalgic/angry/focus/party）。
    创建 M3U8 播放列表并通过 foobar2000 播放，返回播放结果（JSON格式）。"""
    from agents.librarian import get_librarian
    agent = get_librarian()

    if not agent.songs:
        agent.scan_library()

    try:
        from core.emotion_analyzer_simple import SimpleEmotionAnalyzer
        analyzer = SimpleEmotionAnalyzer()
    except ImportError:
        return json.dumps({"status": "error", "message": "情绪分析模块加载失败"},
                          ensure_ascii=False)

    emotion_names = {
        'happy': '快乐', 'sad': '悲伤', 'energetic': '激情',
        'calm': '平静', 'romantic': '浪漫', 'nostalgic': '怀旧',
        'angry': '愤怒', 'focus': '专注', 'party': '派对',
    }
    emotion_display = emotion_names.get(emotion, emotion)

    matched_objects = []
    for song in agent.songs.values():
        cache_key = analyzer._get_file_hash(song.file_path)
        if cache_key in analyzer._cache:
            cached = analyzer._cache[cache_key]
            if cached.get('emotion') == emotion:
                matched_objects.append(song)

    if not matched_objects:
        return json.dumps({"status": "not_found",
                           "message": f"暂无标记为「{emotion_display}」的歌曲。请先运行「分析情绪」来分析你的音乐库。"},
                          ensure_ascii=False)

    from graph.utils import load_config
    config = load_config()
    playlist_name = f"{emotion_display}_{len(matched_objects)}首"
    playlist_path = _create_m3u8_playlist(matched_objects, playlist_name, config)
    foobar_result = _play_with_foobar2000(str(playlist_path))

    return json.dumps({
        "status": "playing" if foobar_result else "playlist_only",
        "emotion": emotion,
        "emotion_display": emotion_display,
        "total": len(matched_objects),
        "playlist": str(playlist_path),
        "playlist_name": playlist_name,
        "foobar": foobar_result,
        "message": (f"🎵 正在播放全部 {len(matched_objects)} 首「{emotion_display}」歌曲！\n📋 {playlist_name}"
                    if foobar_result else
                    f"✅ {emotion_display} 播放列表已创建！\n🎵 {len(matched_objects)} 首歌曲\n💾 {playlist_path}"),
    }, ensure_ascii=False)


@tool
def play_random(count: int = 5, emotion: str = "", language: str = "") -> str:
    """随机播放指定数量、情绪、语言的歌曲。
    count=播放数量，emotion=情绪英文名(可选)，language=语言名(可选)。
    至少指定 emotion 或 language 之一。
    返回播放结果（JSON格式）。"""
    from agents.librarian import get_librarian

    agent = get_librarian()
    if not agent.songs:
        agent.scan_library()

    songs = list(agent.songs.values())
    if not songs:
        return json.dumps({"status": "empty", "message": "音乐库为空"}, ensure_ascii=False)

    # 按情绪筛选
    if emotion:
        from core.emotion_analyzer_simple import SimpleEmotionAnalyzer
        from core.music_library_db import get_library_db
        analyzer = SimpleEmotionAnalyzer()
        lib_db = get_library_db()
        matched = []
        for s in songs:
            cache_key = analyzer._get_file_hash(s.file_path)
            if cache_key in analyzer._cache:
                if analyzer._cache[cache_key].get("emotion") == emotion:
                    matched.append(s)
                    continue
            record = lib_db.get_record(s.artist, s.title)
            if record and record.emotion == emotion:
                matched.append(s)
        songs = matched

    # 按语言筛选
    if language:
        from core.language_detector import detector
        from core.music_library_db import get_library_db
        lib_db = get_library_db()
        matched = []
        for s in songs:
            record = lib_db.get_record(s.artist, s.title)
            lang = record.language if (record and record.language) else None
            if not lang:
                lang, _, _ = detector.detect(s.title, s.artist, s.file_path)
            if lang == language:
                matched.append(s)
        songs = matched

    if not songs:
        cond = f"{emotion}+{language}" if emotion and language else (emotion or language)
        return json.dumps({"status": "not_found", "message": f"没有同时满足 {cond} 的歌曲"}, ensure_ascii=False)

    count = min(count, len(songs))
    picked = random.sample(songs, count)

    from graph.utils import load_config
    config = load_config()
    playlist_name = f"随机{count}首"
    playlist_path = _create_m3u8_playlist(picked, playlist_name, config)
    foobar_result = _play_with_foobar2000(str(playlist_path))

    song_list = [f"{s.artist} - {s.title}" for s in picked]
    return json.dumps({
        "status": "playing" if foobar_result else "playlist_only",
        "total": count,
        "songs": song_list,
        "playlist": str(playlist_path),
        "message": f"🎵 随机播放 {count} 首歌曲\n" + "\n".join(f"  {i+1}. {t}" for i, t in enumerate(song_list)),
    }, ensure_ascii=False, indent=2)


LIBRARIAN_TOOLS = [search_music, scan_library, get_song_info, get_library_stats,
                   play_song, play_all_songs, play_by_artist,
                   play_by_language, play_by_emotion, play_random]
