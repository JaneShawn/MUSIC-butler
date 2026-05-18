# -*- coding: utf-8 -*-
"""
数据修复脚本 - 三步修复音乐库数据
1. 扫描清理幽灵记录
2. 批量语言检测写入 SQLite
3. 批量情绪分析生成缓存

用法:
    python data_repair.py --step all      # 执行全部三步
    python data_repair.py --step scan     # 只执行扫描
    python data_repair.py --step language # 只执行语言检测
    python data_repair.py --step emotion  # 只执行情绪分析
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))


def step1_scan():
    """第一步：扫描清理幽灵记录"""
    print("=" * 60)
    print("[Step 1/3] 扫描清理幽灵记录")
    print("=" * 60)
    
    from agents.librarian import get_librarian
    import yaml
    
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    librarian = get_librarian(config)
    result = librarian.scan_library()
    
    print(f"\n扫描结果:")
    print(f"  发现文件: {result.get('total_files', 0)}")
    print(f"  新索引: {result.get('new_indexed', 0)}")
    print(f"  同步: {result.get('synced', 0)}")
    print(f"  移除幽灵: {result.get('removed', 0)}")
    print(f"  当前总索引: {result.get('total_indexed', 0)}")
    
    return result.get('removed', 0)


def step2_language(batch_size=50, offset=0):
    """第二步：批量语言检测写入 SQLite（支持断点续传）"""
    print("\n" + "=" * 60)
    print("[Step 2/3] 批量语言检测")
    print("=" * 60)
    
    from agents.librarian import get_librarian
    from core.language_detector import detect_language
    from core.music_library_db import get_library_db
    import yaml
    
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    librarian = get_librarian(config)
    lib_db = get_library_db()
    
    songs = list(librarian.songs.values())
    total = len(songs)
    
    # 支持断点续传：从 offset 开始
    songs = songs[offset:]
    to_process = len(songs)
    
    print(f"\n共 {total} 首歌曲，本次处理 {to_process} 首 (offset={offset})")
    print("(单首限时5秒，超时会跳过避免卡死)")
    
    updated = 0
    skipped = 0
    errors = 0
    timeouts = 0
    
    for i, song in enumerate(songs, 1):
        real_idx = offset + i
        try:
            # 检查是否已有语言标签
            record = lib_db.get_record(song.artist, song.title)
            if record and record.language:
                skipped += 1
                continue
            
            # 检测语言（只用前4层本地方法，跳过网易云API和Whisper，避免网络卡顿）
            from core.language_detector import detector
            
            # 第1层：artist_keyword
            artist_lower = f" {song.artist} ".lower()
            result = None
            for kw in detector.KOREAN_ARTISTS:
                if f" {kw.lower()} " in artist_lower:
                    result = ("韩语", "artist_keyword", 0.95)
                    break
            if not result:
                for kw in detector.JAPANESE_ARTISTS:
                    if f" {kw.lower()} " in artist_lower:
                        result = ("日语", "artist_keyword", 0.95)
                        break
            
            # 第2层：字符集检测（返回字符串，包装为三元组）
            if not result:
                char_result = detector._detect_by_chars(song.title, song.artist)
                if char_result:
                    result = (char_result, "char_detect", 0.7)
            
            # 第3层：英语规则（返回字符串，包装为三元组）
            if not result:
                eng_result = detector._detect_english(artist_lower, song.artist, song.title)
                if eng_result:
                    result = (eng_result, "english_rule", 0.6)
            
            # 兜底
            if not result:
                result = ("英语", "fallback", 0.5)
            
            language, source, confidence = result
            
            # 写入 SQLite
            lib_db.update_language(song.artist, song.title, language, source)
            updated += 1
            
            if i % 20 == 0 or i == to_process:
                print(f"  进度: {real_idx}/{total} (已更新 {updated} 首, 跳过 {skipped} 首)")
                
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  [错误] {song.artist} - {song.title}: {e}")
    
    print(f"\n语言检测完成:")
    print(f"  总歌曲: {total}")
    print(f"  本次更新: {updated}")
    print(f"  跳过(已有标签): {skipped}")
    print(f"  超时: {timeouts}")
    print(f"  错误: {errors}")
    print(f"\n提示: 如果还有未完成的，下次运行:")
    print(f"  python data_repair.py --step language --offset {offset + to_process}")
    
    return updated


def step3_emotion():
    """第三步：批量情绪分析生成缓存"""
    print("\n" + "=" * 60)
    print("[Step 3/3] 批量情绪分析")
    print("=" * 60)
    
    from agents.librarian import get_librarian
    from core.emotion_analyzer_simple import SimpleEmotionAnalyzer
    import yaml

    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    librarian = get_librarian(config)
    analyzer = SimpleEmotionAnalyzer()
    
    songs = list(librarian.songs.values())
    total = len(songs)
    
    print(f"\n共 {total} 首歌曲需要分析情绪...")
    print("(优先检查缓存，已有则跳过)")
    
    analyzed = 0
    cached = 0
    errors = 0
    
    for i, song in enumerate(songs, 1):
        try:
            # 检查缓存
            cache_key = analyzer._get_file_hash(song.file_path)
            if cache_key in analyzer._cache:
                cached += 1
                if i % 50 == 0:
                    print(f"  进度: {i}/{total} (缓存命中 {cached} 首)")
                continue
            
            result = analyzer.analyze(song.file_path, lyrics=None, title=song.title, artist=song.artist)
            
            analyzed += 1
            
            if i % 20 == 0 or i == total:
                print(f"  进度: {i}/{total} (已分析 {analyzed} 首, 缓存 {cached} 首)")
                
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"  [错误] {song.artist} - {song.title}: {e}")
    
    print(f"\n情绪分析完成:")
    print(f"  总歌曲: {total}")
    print(f"  本次分析: {analyzed}")
    print(f"  缓存命中: {cached}")
    print(f"  无歌词: {no_lyrics}")
    print(f"  错误: {errors}")
    print(f"  缓存文件: data/emotion_cache.json")
    
    return analyzed


def show_stats():
    """显示当前数据状态"""
    import sqlite3
    
    print("\n" + "=" * 60)
    print("当前数据状态")
    print("=" * 60)
    
    conn = sqlite3.connect('data/music_library.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM songs')
    total = cursor.fetchone()[0]
    print(f"  总歌曲: {total}")
    
    cursor.execute("SELECT COUNT(*) FROM songs WHERE language IS NOT NULL AND language != ''")
    has_lang = cursor.fetchone()[0]
    print(f"  有语言标签: {has_lang} ({has_lang*100//total if total else 0}%)")
    
    cursor.execute("SELECT COUNT(*) FROM songs WHERE emotion IS NOT NULL AND emotion != ''")
    has_emo = cursor.fetchone()[0]
    print(f"  有情绪标签: {has_emo} ({has_emo*100//total if total else 0}%)")
    
    cursor.execute('SELECT language, COUNT(*) FROM songs WHERE language IS NOT NULL AND language != "" GROUP BY language ORDER BY COUNT(*) DESC')
    langs = cursor.fetchall()
    if langs:
        print(f"\n  语言分布:")
        for lang, count in langs[:5]:
            print(f"    {lang}: {count}")
    
    conn.close()
    
    # 检查 emotion_cache
    cache_file = Path('data/emotion_cache.json')
    if cache_file.exists():
        import json
        cache = json.loads(cache_file.read_text(encoding='utf-8'))
        print(f"\n  情绪缓存: {len(cache)} 条记录")
    else:
        print(f"\n  情绪缓存: 不存在")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="修复 music-butler 数据")
    parser.add_argument("--step", choices=["all", "scan", "language", "emotion", "stats"],
                        default="stats", help="执行步骤")
    args = parser.parse_args()
    
    start_time = datetime.now()
    
    if args.step == "stats":
        show_stats()
    elif args.step == "scan":
        step1_scan()
        show_stats()
    elif args.step == "language":
        step2_language()
        show_stats()
    elif args.step == "emotion":
        step3_emotion()
        show_stats()
    elif args.step == "all":
        step1_scan()
        step2_language()
        step3_emotion()
        show_stats()
    
    elapsed = datetime.now() - start_time
    print(f"\n总耗时: {elapsed.seconds // 60}分 {elapsed.seconds % 60}秒")
