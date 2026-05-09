# -*- coding: utf-8 -*-
"""PlayHandlers - handler mixin for MusicAgentChat."""
from typing import Dict, Any, Optional
class PlayHandlers:
    """Handler methods mixed into MusicAgentChat."""

    def handle_query(self, params: Dict) -> str:
        query = params.get("query", "")
        print(f"正在搜索: {query}")
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        results = self.librarian.query(query, top_k=5)
        self.context.set_query_results(results)
        
        if not results:
            return "没有找到匹配的歌曲。"
        
        lines = [f"  {i}. 《{r['song'].title}》- {r['song'].artist}" for i, r in enumerate(results, 1)]
        return f"找到 {len(results)} 首歌曲（输入序号或'第一首'选择）：\n" + "\n".join(lines)
    

    def handle_playlist_from_results(self, params: Dict) -> str:
        """将上次查询结果生成播放列表并播放"""
        if not self.context.last_query_results:
            return "没有可播放的歌曲列表"
        
        results = self.context.last_query_results
        songs = [item.get('song') for item in results if item.get('song')]
        
        if not songs:
            return "列表中没有有效歌曲"
        
        timestamp = datetime.now().strftime("%m%d_%H%M")
        playlist_name = f"推荐歌单_{timestamp}_{len(songs)}首"
        playlist_path = self._create_m3u8_playlist(songs, playlist_name)
        
        # 调用foobar2000播放
        foobar_result = self._play_with_foobar2000(str(playlist_path))
        
        if foobar_result:
            return f"""
🎵 正在播放全部 {len(songs)} 首歌！

📋 {playlist_name}
💾 {playlist_path}
🎧 {foobar_result}

💡 歌单已保存，下次可直接在foobar2000中打开
"""
        else:
            return f"""
✅ 播放列表已创建！

📋 {playlist_name}
🎵 {len(songs)} 首歌曲
💾 {playlist_path}

💡 未找到foobar2000，请手动导入播放列表
"""
    

    def handle_play_by_artist(self, params: Dict) -> str:
        """播放某歌手的全部歌曲（一键播放，不返回列表）"""
        artist = params.get("artist", "")
        if not artist:
            return "请告诉我歌手名称"
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        # 使用 librarian 的 artist 过滤获取全部歌曲
        intent = {"artist": artist}
        results = self.librarian._filter_by_artist(intent, top_k=1000)
        
        if not results:
            return f"未找到 {artist} 的歌曲"
        
        songs = [r["song"] for r in results]
        
        # 生成播放列表
        playlist_name = f"{artist}_全集_{len(songs)}首"
        playlist_path = self._create_m3u8_playlist(songs, playlist_name)
        
        # 调用 foobar2000 播放
        foobar_result = self._play_with_foobar2000(str(playlist_path))
        
        if foobar_result:
            return f"""
🎵 正在播放 {artist} 的全部 {len(songs)} 首歌！

💾 {playlist_path}
🎧 {foobar_result}

💡 歌单已保存，下次可直接在 foobar2000 中打开
"""
        else:
            return f"""
✅ {artist} 播放列表已创建！

🎵 {len(songs)} 首歌曲
💾 {playlist_path}

💡 未找到 foobar2000，请手动导入播放列表
"""
    

    def handle_play_all(self, params: Dict) -> str:
        """播放音乐库中全部歌曲"""
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        songs = list(self.librarian.songs.values())
        if not songs:
            return "音乐库为空"
        
        # 生成播放列表
        playlist_name = f"全部歌曲_{len(songs)}首"
        playlist_path = self._create_m3u8_playlist(songs, playlist_name)
        
        # 调用 foobar2000 播放
        foobar_result = self._play_with_foobar2000(str(playlist_path))
        
        if foobar_result:
            return f"""
🎵 正在播放全部 {len(songs)} 首歌！

💾 {playlist_path}
🎧 {foobar_result}

💡 歌单已保存，下次可直接在 foobar2000 中打开
"""
        else:
            return f"""
✅ 全部歌曲播放列表已创建！

🎵 {len(songs)} 首歌曲
💾 {playlist_path}

💡 未找到 foobar2000，请手动导入播放列表
"""
    

    def handle_batch_select(self, params: Dict) -> str:
        """将用户多选的结果生成播放列表并播放"""
        indices = params.get("indices", [])
        
        if not self.context.last_query_results:
            return "没有可播放的歌曲列表"
        
        if not indices:
            return "没有选择任何歌曲"
        
        results = self.context.last_query_results
        selected = []
        for idx in indices:
            if 0 <= idx < len(results):
                song = results[idx].get('song')
                if song:
                    selected.append(song)
        
        if not selected:
            return "选择的位置没有有效歌曲"
        
        timestamp = datetime.now().strftime("%m%d_%H%M")
        playlist_name = f"自选歌单_{timestamp}_{len(selected)}首"
        playlist_path = self._create_m3u8_playlist(selected, playlist_name)
        
        # 调用foobar2000播放
        foobar_result = self._play_with_foobar2000(str(playlist_path))
        
        # 构建选中歌曲列表
        song_list = "\n".join([f"  {i+1}. {s.artist} - {s.title}" for i, s in enumerate(selected)])
        
        if foobar_result:
            return f"""
🎵 正在播放选中的 {len(selected)} 首歌！

📋 {playlist_name}
{song_list}
💾 {playlist_path}
🎧 {foobar_result}

💡 歌单已保存，下次可直接在foobar2000中打开
"""
        else:
            return f"""
✅ 播放列表已创建！

📋 {playlist_name}
{song_list}
🎵 {len(selected)} 首歌曲
💾 {playlist_path}

💡 未找到foobar2000，请手动导入播放列表
"""
    

    def handle_play_by_name(self, params: Dict) -> str:
        """通过歌名播放歌曲"""
        raw_name = params.get("song_name", "")
        if not raw_name:
            return "请告诉我歌曲名称"
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        # 清洗歌名（去除书名号、歌手名后缀等）
        song_name = self._clean_play_name(raw_name)
        
        # 查找匹配的歌曲（三级递进）
        matched_songs = []
        
        # L1: 精确子串匹配
        for song in self.librarian.songs.values():
            if song_name.lower() in song.title.lower() or \
               song_name.lower() in f"{song.artist} - {song.title}".lower():
                matched_songs.append(song)
        
        # L2: 模糊匹配（L1 无结果时，容错同音字/形近字）
        if not matched_songs and len(song_name) >= 2:
            from difflib import SequenceMatcher
            best_matches = []
            for song in self.librarian.songs.values():
                title_sim = SequenceMatcher(None, song_name.lower(), song.title.lower()).ratio()
                full_sim = SequenceMatcher(None, song_name.lower(), f"{song.artist} {song.title}".lower()).ratio()
                max_sim = max(title_sim, full_sim)
                if max_sim >= 0.6:
                    best_matches.append((max_sim, song))
            
            if best_matches:
                best_matches.sort(key=lambda x: x[0], reverse=True)
                matched_songs = [s for _, s in best_matches[:5]]
        
        # L3: 降级处理（处理 "播放xxx的歌" 被误识别为 play_by_name 的情况）
        if not matched_songs:
            # 检测是否包含情绪关键词，直接转 playlist
            emotion_keywords = {
                '开心': 'happy', '快乐': 'happy', '悲伤': 'sad', '难过': 'sad',
                '安静': 'calm', '平静': 'calm', '浪漫': 'romantic', '激情': 'energetic',
                '燃': 'energetic', '热血': 'energetic', '怀旧': 'nostalgic', '经典': 'nostalgic',
                '愤怒': 'angry', '专注': 'focus', '工作': 'focus', '派对': 'party', '嗨': 'party',
            }
            detected_emotion = None
            for kw, emo in emotion_keywords.items():
                if kw in raw_name:
                    detected_emotion = emo
                    break
            
            if detected_emotion:
                return self.handle_playlist({"mode": "emotion", "emotion": detected_emotion})
            
            # 否则降级为 query 搜索
            query_results = self.librarian.query(raw_name, top_k=5)
            if query_results:
                self.context.set_query_results(query_results)
                lines = [f"  {i}. 《{r['song'].title}》- {r['song'].artist}" for i, r in enumerate(query_results, 1)]
                return f"找到 {len(query_results)} 首相关歌曲（输入序号或'第一首'选择）：\n" + "\n".join(lines)
            return f"未找到包含 '{raw_name}' 的歌曲"
        
        if len(matched_songs) == 1:
            song = matched_songs[0]
            return self._play_song(song)
        else:
            # 多首匹配，显示列表让用户选择
            songs_text = "\n".join([f"{i+1}. {s.artist} - {s.title}" for i, s in enumerate(matched_songs[:10])])
            self.context.last_query_results = [{"song": s} for s in matched_songs]
            return f"找到 {len(matched_songs)} 首相关歌曲，请输入序号播放：\n{songs_text}"
    
    def _play_song(self, song) -> str:
        """播放指定歌曲"""
        foobar_result = self._play_with_foobar2000(song.file_path)
        
        if foobar_result:
            return f"🎵 正在播放: {song.artist} - {song.title}\n{foobar_result}"
        else:
            return f"🎵 {song.artist} - {song.title}\n文件: {song.file_path}\n\n💡 未找到 foobar2000，请手动播放或配置播放器路径"
    

    def handle_play(self, params: Dict) -> str:
        item = params.get("item", {})
        song = item.get('song', item)
        return self._play_song(song)
    
    def _play_with_foobar2000(self, file_path: str) -> Optional[str]:
        """调用 foobar2000 播放指定文件"""
        # 常见安装路径
        foobar_paths = [
            r"C:\Program Files\foobar2000\foobar2000.exe",
            r"C:\Program Files (x86)\foobar2000\foobar2000.exe",
            shutil.which("foobar2000"),  # PATH 中
        ]
        
        foobar_exe = None
        for path in foobar_paths:
            if path and os.path.exists(path):
                foobar_exe = path
                break
        
        if not foobar_exe:
            return None
        
        try:
            # /immediate - 立即播放，如果 foobar2000 未运行会启动它
            subprocess.Popen(
                [foobar_exe, "/immediate", file_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False
            )
            return f"📱 已通过 foobar2000 播放"
        except Exception as e:
            return f"⚠️ 调用播放器失败: {e}"
    

    def handle_query_emotion_songs(self, params: Dict) -> str:
        """查询本地库中特定情绪的歌曲"""
        emotion = params.get("emotion", "happy")
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        # 加载情绪分析器
        try:
            from core.emotion_analyzer_simple import SimpleEmotionAnalyzer as AudioEmotionAnalyzer
        except ImportError:
            return "情绪分析模块加载失败"
        
        analyzer = AudioEmotionAnalyzer()
        
        # 查找缓存中该情绪的歌曲
        emotion_names = {
            'happy': '快乐', 'sad': '悲伤', 'energetic': '激情',
            'calm': '平静', 'romantic': '浪漫', 'nostalgic': '怀旧',
            'angry': '愤怒', 'focus': '专注', 'party': '派对'
        }
        emotion_name = emotion_names.get(emotion, emotion)
        
        matching_songs = []
        
        for song in self.librarian.songs.values():
            cache_key = analyzer._get_file_hash(song.file_path)
            if cache_key in analyzer._cache:
                cached = analyzer._cache[cache_key]
                if cached.get('emotion') == emotion:
                    matching_songs.append({
                        'title': song.title or Path(song.file_path).stem,
                        'artist': song.artist or 'Unknown',
                        'confidence': cached.get('confidence', 0)
                    })
        
        if not matching_songs:
            return f"暂无标记为「{emotion_name}」的歌曲。\n请先运行「分析情绪」来分析你的音乐库。"
        
        # 按置信度排序
        matching_songs.sort(key=lambda x: x['confidence'], reverse=True)
        
        # 显示结果
        lines = [f"🎵 你的音乐库中有 {len(matching_songs)} 首「{emotion_name}」的歌曲：", ""]
        
        for i, song in enumerate(matching_songs[:15], 1):  # 最多显示15首
            conf_emoji = "⭐" if song['confidence'] > 0.7 else ""
            lines.append(f"{i}. 《{song['title']}》- {song['artist']} {conf_emoji}")
        
        if len(matching_songs) > 15:
            lines.append(f"\n...还有 {len(matching_songs) - 15} 首")
        
        lines.append(f"\n💡 可以对我说「创建一个{emotion_name}的播放列表」生成foobar2000歌单")
        
        return "\n".join(lines)
    

    def handle_query_language_songs(self, params: Dict) -> str:
        """查询本地库中特定语言的歌曲"""
        language = params.get("language", "韩语")
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        # 使用language_detector检测语言
        from core.language_detector import detector
        
        matching_songs = []
        
        for song in self.librarian.songs.values():
            lang, source, conf = detector.detect(song.title, song.artist, song.file_path)
            if lang == language:
                matching_songs.append({
                    'title': song.title or Path(song.file_path).stem,
                    'artist': song.artist or 'Unknown',
                    'source': source,
                    'confidence': conf
                })
        
        if not matching_songs:
            return f"暂无检测到「{language}」歌曲。"
        
        # 按置信度排序
        matching_songs.sort(key=lambda x: x['confidence'], reverse=True)
        
        # 显示结果
        lines = [f"🎵 你的音乐库中有 {len(matching_songs)} 首「{language}」歌曲：", ""]
        
        for i, song in enumerate(matching_songs[:20], 1):  # 最多显示20首
            conf_emoji = "⭐" if song['confidence'] > 0.8 else ""
            lines.append(f"{i}. 《{song['title']}》- {song['artist']} {conf_emoji}")
        
        if len(matching_songs) > 20:
            lines.append(f"\n...还有 {len(matching_songs) - 20} 首")
        
        lines.append(f"\n💡 提示：可以对我说「标记 歌手 - 歌名 为 英语」来纠正语言")

        return "\n".join(lines)


    def handle_play_all_results(self, params: Dict) -> str:
        """Play all songs from the last query results."""
        if not self.context.last_query_results:
            return "没有可播放的歌曲列表，请先查询。"
        results = self.context.last_query_results
        songs = [item.get('song') for item in results if item.get('song')]
        if not songs:
            return "列表中没有有效歌曲。"

        from datetime import datetime
        timestamp = datetime.now().strftime("%m%d_%H%M")
        playlist_name = f"查询全播_{timestamp}_{len(songs)}首"
        playlist_path = self._create_m3u8_playlist(songs, playlist_name)
        foobar_result = self._play_with_foobar2000(str(playlist_path))
        if foobar_result:
            return f"🎵 正在播放全部 {len(songs)} 首歌！\n📋 {playlist_name}\n💾 {playlist_path}\n🎧 {foobar_result}"
        return f"已创建播放列表: {playlist_path}"

    def handle_play_all_except(self, params: Dict) -> str:
        """Play all songs from last query results except the specified one."""
        songs = params.get("songs", [])
        excluded = params.get("excluded", -1)
        if not songs:
            return "没有可播放的歌曲。"

        from datetime import datetime
        timestamp = datetime.now().strftime("%m%d_%H%M")
        playlist_name = f"排除第{excluded + 1}首_{timestamp}_{len(songs)}首"
        playlist_path = self._create_m3u8_playlist(songs, playlist_name)
        foobar_result = self._play_with_foobar2000(str(playlist_path))
        if foobar_result:
            return f"🎵 正在播放 {len(songs)} 首歌（已跳过第 {excluded + 1} 首）！\n📋 {playlist_name}"
        return f"已创建播放列表: {playlist_path}"

