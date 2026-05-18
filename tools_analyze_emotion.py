#!/usr/bin/env python3
"""
批量分析音乐库情绪标签工具
支持轻量版（无需编译）
"""
import sys
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agents.librarian import LibrarianAgent

# 尝试导入完整版，失败则用轻量版
try:
    from core.emotion_analyzer import AudioEmotionAnalyzer
    print("[INFO] Using full emotion analyzer (Essentia)")
except ImportError:
    from core.emotion_analyzer_simple import SimpleEmotionAnalyzer as AudioEmotionAnalyzer
    print("[INFO] Using simple emotion analyzer (pydub)")

# 导入歌词获取器（已移除，使用纯音频分析）

try:
    from core.kimi_client import KimiClient
except ImportError:
    KimiClient = None


def main():
    print("=" * 60)
    print("Music Emotion Analyzer")
    print("=" * 60)
    
    with open("config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    print("\n[1/4] Initializing music library...")
    from agents.librarian import get_librarian
    librarian = get_librarian(config)
    
    if not librarian.songs:
        print("正在扫描音乐文件...")
        librarian.run("scan")
    
    total = len(librarian.songs)
    print(f"Library: {total} songs")
    
    # 初始化 Kimi
    kimi = None
    if KimiClient:
        try:
            from graph.utils import load_config
            kimi = KimiClient(config=load_config())
            print("[OK] Kimi API connected")
        except (ValueError, Exception):
            print("[WARN] Kimi API not available")
    
    # 初始化分析器
    analyzer = AudioEmotionAnalyzer(kimi_client=kimi)

    # 准备歌曲列表
    songs_to_analyze = []
    for song_id, song in librarian.songs.items():
        songs_to_analyze.append({
            'file_path': song.file_path,
            'title': song.title,
            'artist': song.artist,
            'lyrics': None
        })

    print(f"\n[2/3] Analyzing {len(songs_to_analyze)} songs...\n")
    
    analyzed = 0
    emotion_stats = {}
    
    def progress_callback(current, total):
        if current % 10 == 0 or current == total:
            print(f"  进度: {current}/{total} ({current/total*100:.1f}%)")
    
    results = analyzer.batch_analyze(songs_to_analyze, progress_callback)
    
    # 统计
    for file_path, result in results.items():
        emotion = result.emotion
        emotion_stats[emotion] = emotion_stats.get(emotion, 0) + 1
    
    print("\n" + "=" * 60)
    print("Emotion Distribution")
    print("=" * 60)
    
    emotion_names = {
        'happy': '快乐', 'sad': '悲伤', 'energetic': '激情',
        'calm': '平静', 'romantic': '浪漫', 'nostalgic': '怀旧',
        'angry': '愤怒', 'focus': '专注', 'party': '派对'
    }
    
    for emotion, count in sorted(emotion_stats.items(), key=lambda x: -x[1]):
        name = emotion_names.get(emotion, emotion)
        bar = "█" * (count * 30 // total)
        print(f"  {name:6} | {bar:30} | {count:3}首 ({count/total*100:.1f}%)")

    print("\n[OK] Analysis complete!")
    print("\nYou can now create emotion playlists:")
    print('   - "创建一个快乐的播放列表"')
    print('   - "创建一个专注的歌单"')
    print('\nTip: Place .lrc files next to your music files for better accuracy!')


if __name__ == "__main__":
    main()
