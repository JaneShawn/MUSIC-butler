# -*- coding: utf-8 -*-
"""AnalyzeHandlers - handler mixin for MusicAgentChat."""
import os
from pathlib import Path
from typing import Dict, Any
class AnalyzeHandlers:
    """Handler methods mixed into MusicAgentChat."""

    def handle_analyze(self, params: Dict) -> str:
        print("正在分析音乐库...")
        analysis = self.organizer.run("analyze")
        top = analysis.get('top_artists', [])[:5]
        artists = "\n".join([f"  • {a}: {c}首" for a, c in top])
        return f"""音乐库分析：
• 总歌曲: {analysis['total_songs']} 首
• 艺术家: {analysis['artists_count']} 位
• 流派: {analysis['genres_count']} 种

Top 5 艺术家：
{artists}

推荐: {analysis['suggestion']}"""
    

    def handle_show_language_stats(self, params: Dict) -> str:
        """显示语言统计"""
        from core.language_detector import detector
        
        if not self.librarian.songs:
            return "请先扫描音乐库"
        
        # 检测所有歌曲（使用缓存）
        print("正在统计语言分布...")
        for song in self.librarian.songs.values():
            detector.detect(song.title, song.artist, song.file_path)
        
        stats = detector.get_stats()
        total = sum(stats.values())
        
        lines = ["📊 歌曲语言分布统计", "=" * 40]
        for lang, count in stats.items():
            bar = "█" * (count * 30 // total if total > 0 else 0)
            lines.append(f"  {lang:6} | {bar:30} | {count}首")
        lines.append("=" * 40)
        lines.append(f"总计: {total} 首")
        lines.append("")
        lines.append("💡 操作命令:")
        lines.append("  有哪些韩语歌 - 查询韩语歌曲")
        lines.append("  标记 IU - Blueming 为 韩语 - 纠正语言")
        lines.append("  导出语言 - 导出CSV批量编辑")
        
        return "\n".join(lines)
    

    def handle_detect_single_language(self, params: Dict) -> str:
        """检测单首歌曲的语言（详细版）"""
        from core.language_detector import detect_language
        from core.audio_language_detector import detect_audio_language
        
        song_name = params.get("song_name", "")
        if not song_name:
            return "请告诉我歌曲名称，例如：检测BTS语言"
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        # 查找歌曲
        matched = []
        for song in self.librarian.songs.values():
            if song_name.lower() in song.title.lower() or \
               song_name.lower() in f"{song.artist} {song.title}".lower():
                matched.append(song)
        
        if not matched:
            return f"未找到包含 '{song_name}' 的歌曲"
        
        if len(matched) > 1:
            songs_list = "\n".join([f"  {i+1}. {s.artist} - {s.title}" for i, s in enumerate(matched[:10])])
            return f"找到多首匹配歌曲，请输入序号选择：\n{songs_list}\n\n或直接说：检测 BTS - Dynamite 语言"
        
        song = matched[0]
        
        print(f"🔍 检测歌曲语言: {song.artist} - {song.title}")
        print("-" * 50)
        
        # 1. 快速检测（文本分析）
        print("\n[1/3] 快速检测（歌手名+网易云API）...")
        lang, source, conf = detect_language(song.title, song.artist, song.file_path)
        print(f"  结果: {lang} (来源: {source}, 置信度: {conf:.2f})")
        
        # 2. 音频检测（Whisper）
        print("\n[2/3] 音频检测（分析歌曲内容）...")
        audio_lang, audio_conf = detect_audio_language(song.file_path)
        if audio_lang:
            print(f"  结果: {audio_lang} (置信度: {audio_conf:.2f})")
        else:
            print("  音频检测失败")
        
        # 3. 综合结论
        print("\n[3/3] 综合判断...")
        print("-" * 50)
        
        # 确定最终语言（优先音频识别，更准）
        final_lang = audio_lang if audio_lang and audio_conf > conf else lang
        final_conf = max(audio_conf if audio_lang else 0, conf)
        
        # 保存到数据库（自动）
        from core.language_detector import detector
        detector.manual_set(song.artist, song.title, final_lang)
        
        # 如果两种方法一致
        if audio_lang and lang == audio_lang:
            return f"""
🎵 {song.artist} - {song.title}

✅ 检测结果: **{lang}**

📊 分析详情:
  • 文本分析: {lang} ({conf:.0%})
  • 音频识别: {audio_lang} ({audio_conf:.0%})

💾 已自动保存到语言数据库！

💡 可用命令:
  • 导出语言 - 生成可编辑文档
  • 有哪些{lang}歌 - 查询同类歌曲
  • 标记 {song.artist} - {song.title} 为 日语 - 如需纠正
"""
        
        # 如果不一致，提示用户
        return f"""
🎵 {song.artist} - {song.title}

⚠️ 检测结果不一致（已保存为: {final_lang}）:

📊 分析详情:
  • 文本分析: {lang} ({conf:.0%})
  • 音频识别: {audio_lang or '失败'} ({audio_conf:.0%} if audio_lang else 0)

💾 已自动保存到语言数据库！

🤔 建议:
  • 当前以{audio_lang or lang}为准（保存在数据库中）
  • 如需纠正: 标记 {song.artist} - {song.title} 为 正确语言
  • 导出语言 - 批量查看和编辑所有结果
"""
    

    def handle_show_library_stats(self, params: Dict) -> str:
        """显示音乐库完整统计"""
        from core.music_library_db import get_library_db
        
        if not self.librarian.songs:
            return "请先扫描音乐库"
        
        lib_db = get_library_db()
        stats = lib_db.get_stats()
        
        lines = [
            "📊 音乐库完整统计",
            "=" * 50,
            f"总歌曲: {stats['total']} 首",
            "",
            "🌍 语言分布:"
        ]
        
        for lang, count in list(stats['languages'].items())[:8]:
            bar = "█" * (count * 30 // stats['total'] if stats['total'] > 0 else 0)
            lines.append(f"  {lang:8} | {bar:30} | {count}首")
        
        if len(stats['languages']) > 8:
            lines.append(f"  ... 还有 {len(stats['languages']) - 8} 种语言")
        
        lines.extend([
            "",
            "🎭 情绪分布:",
        ])
        
        for emotion, count in list(stats['emotions'].items())[:5]:
            lines.append(f"  {emotion}: {count}首")
        
        lines.extend([
            "",
            f"🎵 有歌词: {stats['lyrics_count']} 首",
            "",
            "💡 操作命令:",
            "  导出文档 - 生成完整Excel表格",
            "  有哪些韩语歌 - 按语言查询",
            "  音频检测语言 - 用AI听歌识语言"
        ])
        
        return "\n".join(lines)
    

    def handle_detect_language_by_audio(self, params: Dict) -> str:
        """只用音频检测语言（Whisper）"""
        from core.audio_language_detector import AudioLanguageDetector
        
        if not self.librarian.songs:
            return "请先扫描音乐库"
        
        total = len(self.librarian.songs)
        print(f"🎵 开始音频语言检测（只用Whisper分析歌曲内容）")
        print(f"   共 {total} 首歌曲，预计需要 {total * 5 // 60} 分钟...")
        print(f"   ⚠️  此过程较慢，但准确度最高！\n")
        
        detector = AudioLanguageDetector()
        results = {}
        
        for i, song in enumerate(self.librarian.songs.values(), 1):
            print(f"[{i}/{total}] {song.artist} - {song.title}")
            lang, conf = detector.detect(song.file_path)
            if lang:
                results[lang] = results.get(lang, 0) + 1
                print(f"      → {lang} ({conf:.2f})")
            
            # 每10首显示进度
            if i % 10 == 0:
                print(f"\n  进度: {i}/{total} ({i*100//total}%)\n")
        
        # 显示结果
        lines = ["\n📊 音频检测结果", "=" * 40]
        for lang, count in sorted(results.items(), key=lambda x: -x[1]):
            lines.append(f"  {lang}: {count}首")
        lines.append("=" * 40)
        lines.append(f"总计: {sum(results.values())} 首")
        lines.append("")
        lines.append("✅ 检测结果已缓存到 data/audio_language_cache.json")
        lines.append("💡 现在可以用 '有哪些韩语歌' 查询了")
        
        return "\n".join(lines)
    

    def handle_analyze_single_emotion(self, params: Dict) -> str:
        """分析单首歌曲的情绪"""
        from core.lyrics_fetcher import LyricsFetcher
        
        song_name = params.get("song_name", "")
        
        # 处理指代词："第x首"、"这首歌"、"它" —— 从上次查询结果中解析
        target_song = None
        if song_name in ["这首歌", "它", "这首", "当前播放的歌", "刚才那首"] or \
           (song_name and song_name.startswith("第") and "首" in song_name):
            if self.context.last_query_results:
                idx = self._parse_multi_select(song_name, len(self.context.last_query_results))
                if idx and len(idx) == 1:
                    # _parse_multi_select 返回的是 0-based 索引，直接使用
                    target_song = self.context.last_query_results[idx[0]].get("song")
                elif not idx and self.context.last_query_results:
                    target_song = self.context.last_query_results[0].get("song")
        
        # 如果没有通过指代词解析到歌曲，正常搜索
        if not target_song:
            if not song_name:
                return "请告诉我歌曲名称（如「分析晴天的情绪」）"
            
            if not self.librarian.songs:
                self.librarian.run("scan")
            
            # 查找匹配的歌曲
            matched_songs = []
            for song in self.librarian.songs.values():
                if song_name.lower() in song.title.lower() or \
                   song_name.lower() in f"{song.artist} - {song.title}".lower():
                    matched_songs.append(song)
            
            if not matched_songs:
                return f"未找到包含 '{song_name}' 的歌曲"
            
            target_song = matched_songs[0]
        
        song = target_song
        
        try:
            from core.emotion_analyzer_simple import SimpleEmotionAnalyzer as AudioEmotionAnalyzer
        except ImportError:
            return "情绪分析模块加载失败"
        
        # 传入Kimi客户端以启用LLM歌词分析
        analyzer = AudioEmotionAnalyzer(kimi_client=self.kimi)
        fetcher = LyricsFetcher(lyrics_dir="data/lyrics")
        
        # 获取歌词（先检查本地，再尝试网易云）
        lyrics = fetcher._from_lyrics_dir(song.title, song.artist)
        if not lyrics:
            # 尝试从网易云获取
            lyrics = fetcher.fetch(song.title, song.artist, song.file_path)
        
        if not lyrics:
            return f"《{song.title}》暂无歌词，无法分析情绪\n建议：先运行「下载歌词」或「识别歌词」"
        
        # 分析情绪（强制重新分析，显示详细日志）
        print(f"正在分析《{song.title}》的情绪...")
        print(f"  歌词长度: {len(lyrics)}字符")
        print(f"  歌词前100字: {lyrics[:100].replace(chr(10), ' ')}...")
        
        # 清除这首歌曲的缓存，强制重新分析
        cache_key = analyzer._get_file_hash(song.file_path)
        if cache_key in analyzer._cache:
            del analyzer._cache[cache_key]
            print(f"  已清除旧缓存，重新分析...")
        
        result = analyzer.analyze(song.file_path, lyrics=lyrics, title=song.title, artist=song.artist, verbose=True)
        
        if not result:
            return f"《{song.title}》情绪分析失败"
        
        emotion = result.emotion if hasattr(result, 'emotion') else result.get("emotion", "unknown")
        confidence = result.confidence if hasattr(result, 'confidence') else result.get("confidence", 0)
        
        # 置信度转换：如果是小数(0-1)转为百分比
        if confidence < 1:
            confidence_pct = int(confidence * 100)
        else:
            confidence_pct = int(confidence)
        
        emotion_names = {
            'happy': '快乐', 'sad': '悲伤', 'energetic': '激情',
            'calm': '平静', 'romantic': '浪漫', 'nostalgic': '怀旧',
            'angry': '愤怒', 'focus': '专注', 'party': '派对'
        }
        emotion_cn = emotion_names.get(emotion, emotion)
        
        return f"""
🎵 《{song.title}》 - {song.artist}

💭 情绪分析结果: **{emotion_cn}**
📊 置信度: {confidence_pct}%

"""
    

    def handle_analyze_emotion(self, params: Dict) -> str:
        """分析音乐库情绪（集成到聊天界面）"""
        try:
            from core.emotion_analyzer_simple import SimpleEmotionAnalyzer as AudioEmotionAnalyzer
        except ImportError:
            return "情绪分析模块加载失败"
        
        from core.lyrics_fetcher import LyricsFetcher
        import os
        
        # 检查是否强制重新分析
        force_reanalyze = params.get("force", False)
        cache_file = Path("data/emotion_cache.json")
        
        if force_reanalyze and cache_file.exists():
            print("🗑️  清除历史情绪缓存...")
            os.remove(cache_file)
            print("✅ 缓存已清除，将重新分析所有歌曲")
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        total = len(self.librarian.songs)
        if total == 0:
            return "音乐库为空"
        
        print(f"[1/3] 准备分析 {total} 首歌曲...")
        
        # 初始化（使用专用歌词目录）
        analyzer = AudioEmotionAnalyzer(kimi_client=self.kimi)
        lyrics_fetcher = LyricsFetcher(lyrics_dir="data/lyrics")
        
        # 准备歌曲数据
        songs_data = []
        for song in self.librarian.songs.values():
            songs_data.append({
                'file_path': song.file_path,
                'title': song.title,
                'artist': song.artist,
                'lyrics': None
            })
        
        total_songs = len(songs_data)
        print(f"[2/3] 正在获取 {total_songs} 首歌曲的歌词...")
        print("      (检查: data/lyrics/ 目录 → 网易云API → 缓存)")
        
        # 获取歌词（分批处理，每批50首）
        batch_size = 50
        lyrics_results = {}
        
        for i in range(0, total_songs, batch_size):
            batch = songs_data[i:i+batch_size]
            batch_lyrics = lyrics_fetcher.batch_fetch(batch)
            lyrics_results.update(batch_lyrics)
            
            if (i + batch_size) % 50 == 0 or (i + batch_size) >= total_songs:
                print(f"      歌词进度: {min(i+batch_size, total_songs)}/{total_songs}")
        
        for song in songs_data:
            if song['file_path'] in lyrics_results:
                song['lyrics'] = lyrics_results[song['file_path']]
        
        lyrics_count = len(lyrics_results)
        print(f"      获取到 {lyrics_count} 首歌词 ({lyrics_count/total_songs*100:.1f}%)")
        
        # 分析情绪
        print(f"[3/3] 正在分析 {total_songs} 首歌曲的情绪...")
        print("      (显示前3首详细分析过程)")
        emotion_stats = {}
        analyzed = 0
        
        for i, song in enumerate(songs_data):
            try:
                # 前3首显示详细日志
                verbose = (i < 3)
                if verbose:
                    print(f"\n  --- 歌曲 {i+1}: {song['title']} ---")
                
                result = analyzer.analyze(
                    song['file_path'],
                    song['lyrics'],
                    song['title'],
                    song['artist'],
                    verbose=verbose
                )
                emotion_stats[result.emotion] = emotion_stats.get(result.emotion, 0) + 1
                analyzed += 1
                
                if analyzed % 50 == 0:
                    print(f"      情绪分析进度: {analyzed}/{total_songs}")
            except Exception as e:
                print(f"      [错误] {song.get('title', '')}: {e}")
        
        print("\n  --- 详细日志结束 ---\n")
        
        # 显示统计
        lines = [f"\n📊 情绪分布统计（共{analyzed}首）", "=" * 40]
        emotion_names = {
            'happy': '快乐', 'sad': '悲伤', 'energetic': '激情',
            'calm': '平静', 'romantic': '浪漫', 'nostalgic': '怀旧',
            'angry': '愤怒', 'focus': '专注', 'party': '派对'
        }
        
        for emotion, count in sorted(emotion_stats.items(), key=lambda x: -x[1]):
            name = emotion_names.get(emotion, emotion)
            bar = "█" * (count * 20 // analyzed if analyzed > 0 else 0)
            lines.append(f"  {name:6} | {bar:20} | {count}首")
        
        lines.append("=" * 40)
        
        # 显示歌词覆盖情况
        no_lyrics = analyzed - lyrics_count
        if no_lyrics > 0:
            lines.append(f"\n💡 其中 {lyrics_count}首有歌词，{no_lyrics}首无歌词")
            lines.append("   无歌词歌曲：依赖音频+歌名推断（可能不够准）")
            lines.append("   改善方法：放置.lrc歌词文件到歌曲目录")
        
        lines.append(f"\n✅ 已分析 {analyzed} 首歌曲并缓存")
        lines.append("现在可以创建情绪播放列表了！")
        
        return "\n".join(lines)
    

