# -*- coding: utf-8 -*-
"""FixHandlers - handler mixin for MusicAgentChat."""
from typing import Dict, Any
from pathlib import Path
class FixHandlers:
    """Handler methods mixed into MusicAgentChat."""

    def handle_fix_metadata(self, params: Dict) -> str:
        confirm = params.get("confirm", False)
        rename = params.get("rename", False)
        download_cover = params.get("download_cover", True)
        from_pending = params.get("from_pending", False)
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        if not from_pending:
            result = self.librarian.fix_metadata(dry_run=True, rename_files=rename, download_cover=False)
            
            if result["incomplete"] == 0:
                return "所有歌曲元数据完整！"
            
            remaining_hint = f"\n• 将分批处理，本次处理 {result.get('processed', result['incomplete'])} 首" if result.get('remaining', 0) > 0 else ""
            
            self.context.set_pending(PendingAction(
                action_type="fix_metadata",
                params={"confirm": True, "rename": rename, "download_cover": download_cover, "from_pending": True},
                description=f"修复元数据{'并下载封面' if download_cover else ''}{'并重命名' if rename else ''}"
            ))
            
            # 分析数据源
            source_stats = result.get('source_stats', {})
            source_details = []
            for key, name in [('qq_music', '🐧 QQ音乐'), ('netease', '☁️ 网易云'), 
                              ('musicbrainz', '🎵 MusicBrainz'), ('llm_parse', '🤖 LLM解析'),
                              ('local_parse', '📄 本地解析')]:
                if source_stats.get(key, 0) > 0:
                    source_details.append(f"{name}: {source_stats[key]}首")
            
            source_text = " | ".join(source_details) if source_details else "未获取到数据源信息"
            
            return f"""元数据检查（预览模式）：
• 总歌曲: {result['total']} 首
• 待修复: {result['incomplete']} 首
• 可识别: {result['fixed']} 首{remaining_hint}

📊 识别来源: {source_text}

💡 说明：
• "可识别"表示能从文件名或在线搜索找到歌曲信息
• 在线搜索优先顺序: QQ音乐 → 网易云 → MusicBrainz
• 实际写入需要确认后才执行
• 仅支持写入 FLAC/MP3/M4A 格式

输入'确认'执行修复，或'取消'放弃。"""
        
        print("正在修复元数据...")
        result = self.librarian.fix_metadata(dry_run=False, rename_files=rename, download_cover=download_cover)
        self.context.clear_pending()
        
        source_stats = result.get('source_stats', {})
        source_display = []
        for key, name in [('local_parse', '本地'), ('llm_parse', 'LLM'), ('qq_music', 'QQ音乐'), 
                          ('netease', '网易云'), ('musicbrainz', 'MusicBrainz')]:
            if source_stats.get(key, 0) > 0:
                source_display.append(f"{name}:{source_stats[key]}")
        
        source_summary = " | ".join(source_display) if source_display else "未知"
        cover_info = f"\n• 嵌入封面: {result.get('covers', 0)} 首" if result.get('covers', 0) > 0 else ""
        remaining_hint = f"\n• 剩余待处理: {result.get('remaining', 0)} 首（再次输入'修复元数据'继续）" if result.get('remaining', 0) > 0 else ""
        
        # 分析写入情况
        written = result.get('written', 0)
        fixed = result.get('fixed', 0)
        skipped = result.get('skipped_write', 0)
        failures = result.get('write_failures', [])
        
        # 构建详细提示
        details = []
        if skipped > 0:
            details.append(f"• 格式不支持跳过: {skipped} 首")
        if failures and written == 0:
            details.append("• 写入失败原因示例:")
            for f in failures[:3]:
                details.append(f"  - {f}")
        
        detail_text = "\n".join(details) if details else ""
        
        if written == 0 and fixed > 0:
            write_hint = f"""
⚠️ 注意：识别成功但未写入文件标签
可能原因：
• 文件格式不支持（仅支持 FLAC/MP3/M4A，不支持 WAV/OGG 等）
• 文件被占用（请关闭音乐播放器）
• 文件权限只读
{detail_text}"""
        elif details:
            write_hint = f"\n{detail_text}"
        else:
            write_hint = ""
        
        return f"""修复完成！
• 本次处理: {result.get('processed', fixed)} 首
• 成功识别: {fixed} 首（从文件名/在线搜索获取信息）
• 写入标签: {written} 首{write_hint}
• 数据来源: {source_summary}{cover_info}{remaining_hint}"""
    

    def handle_fix_single_metadata(self, params: Dict) -> str:
        """修复单曲元数据（指定文件或查询结果中的歌曲）"""
        file_hint = params.get("file")
        from_query = params.get("from_query", False)
        force = params.get("force", False)
        confirm = params.get("confirm", False)
        from_pending = params.get("from_pending", False)
        selected_idx = params.get("selected_idx")
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        # 确定目标歌曲
        target_song = None
        
        # 优先处理 from_pending（确认后的执行）
        if from_pending:
            # 通过 song_id 直接获取歌曲
            song_id = params.get('song_id')
            target_song = self.librarian.songs.get(song_id)
            if not target_song:
                return "❌ 错误：找不到要更新的歌曲，请重新搜索"
        elif selected_idx is not None and self.context.last_query_results:
            # 通过序号选择
            if 0 <= selected_idx < len(self.context.last_query_results):
                target_song = self.context.last_query_results[selected_idx].get('song')
        elif file_hint:
            # 优先精确匹配：从搜索词中提取歌名和歌手
            search_lower = file_hint.lower()
            
            # 1. 先尝试精确匹配（标题或文件名包含搜索词）
            exact_matches = []
            for song_id, song in self.librarian.songs.items():
                file_name = Path(song.file_path).stem.lower()
                title = song.title.lower()
                artist = song.artist.lower()
                
                # 精确包含匹配
                if search_lower in title or search_lower in file_name:
                    # 计算匹配质量（搜索词占标题的比例）
                    match_quality = len(search_lower) / max(len(title), 1)
                    exact_matches.append((song, match_quality, 'title'))
                elif search_lower in artist:
                    exact_matches.append((song, 0.5, 'artist'))  # 歌手匹配权重较低
            
            # 按匹配质量排序
            if exact_matches:
                exact_matches.sort(key=lambda x: x[1], reverse=True)
                target_song = exact_matches[0][0]
                print(f"✓ 精确匹配: {target_song.artist} - {target_song.title}")
            
            # 2. 精确匹配失败，尝试分词匹配（处理"杨千嬅的处处吻"→"杨千嬅"+"处处吻"）
            if not target_song:
                # 尝试提取歌手和歌名
                parts = [p.strip() for p in re.split(r'[的\-\s]', search_lower) if len(p.strip()) > 1]
                
                if len(parts) >= 2:
                    # 可能格式：歌手 + 歌名
                    possible_artist = parts[0]
                    possible_title = parts[-1]
                    
                    for song_id, song in self.librarian.songs.items():
                        artist_match = possible_artist in song.artist.lower().replace(" ", "")
                        title_match = possible_title in song.title.lower().replace(" ", "")
                        
                        if artist_match and title_match:
                            target_song = song
                            print(f"✓ 分词匹配: {target_song.artist} - {target_song.title}")
                            break
            
            # 3. 最后才用RAG向量搜索（容易匹配到相似但不同的歌）
            if not target_song:
                print(f"🔍 正在向量搜索: {file_hint}")
                results = self.librarian.query(file_hint, top_k=5, use_threshold=False)
                
                # 过滤：确保至少有一个关键词匹配（避免匹配到完全不同的歌）
                for result in results:
                    song = result.get('song')
                    if song:
                        # 检查是否有共同词汇
                        search_words = set(search_lower.replace(" ", ""))
                        title_words = set(song.title.lower().replace(" ", ""))
                        artist_words = set(song.artist.lower().replace(" ", ""))
                        
                        # 如果搜索词和标题/歌手有共同字
                        if search_words & title_words or search_words & artist_words:
                            target_song = song
                            print(f"✓ 向量搜索+过滤: {target_song.artist} - {target_song.title}")
                            break
                
                # 还是没找到，用第一个但提示用户
                if not target_song and results:
                    target_song = results[0].get('song')
                    if target_song:
                        print(f"⚠️  最接近的匹配: {target_song.artist} - {target_song.title}（可能不是您要找的歌）")
        elif from_query and self.context.last_query_results:
            # 使用最近一次查询结果的第一首
            target_song = self.context.last_query_results[0].get('song')
        
        if not target_song:
            # 尝试直接用搜索词在线识别（不依赖本地匹配）
            if file_hint and len(file_hint) > 2:
                print(f"🔍 本地未找到匹配，尝试在线识别: {file_hint}")
                from agents.metadata_enhancer import MetadataEnhancer
                enhancer = MetadataEnhancer(kimi_client=self.librarian.kimi if self.librarian.has_llm else None)
                
                metadata = enhancer.search_by_filename(file_hint + ".mp3", download_cover=True)  # 加假扩展名帮助解析
                
                if metadata and metadata.get("title"):
                    # 找到了在线信息，但本地没这首歌，提示用户
                    return f"""🔍 在线识别结果:

搜索词: {file_hint}
识别结果:
• 歌名: {metadata.get('title')}
• 歌手: {metadata.get('artist')}
• 专辑: {metadata.get('album', '未知')}
• 来源: {metadata.get('source', '未知')}

⚠️ 但在本地音乐库中未找到匹配的文件。

可能原因：
• 文件名与搜索词差异较大
• 这首歌不在你的音乐库中

建议：
• 使用'重新识别'列出所有歌曲
• 或检查文件名是否包含歌手和歌名"""
            
            # 交互式选择：列出元数据可疑的歌曲（Unknown 或 force 模式下列出更多）
            if force:
                # 强制模式下，列出所有歌曲供选择
                candidates = list(self.librarian.songs.values())[:20]
                title = "📋 选择要重新识别的歌曲（输入序号）：\n"
            else:
                # 普通模式下，只列出不完整的
                candidates = [s for s in self.librarian.songs.values() 
                             if s.artist == "Unknown" or s.title == "Unknown"]
                title = "📋 找到以下元数据不完整的歌曲（输入序号选择）：\n"
            
            if not candidates:
                return "✅ 所有歌曲元数据都完整！没有需要修复的单曲。\n\n如果现有信息有误，请使用'重新识别'或'强制修复'。"
            
            # 显示候选歌曲
            lines = [title]
            for i, s in enumerate(candidates[:10], 1):
                filename = Path(s.file_path).name
                current = f"[{s.artist} - {s.title}]" if s.artist != "Unknown" else "[Unknown]"
                lines.append(f"  {i}. {filename} {current}")
            
            # 保存到上下文供后续选择
            self.context.set_query_results([{"song": s} for s in candidates[:10]])
            
            hint = "输入序号（如'1'）选择歌曲" if force else "输入序号（如'1'）选择要修复的歌曲"
            return "\n".join(lines) + f"\n\n{hint}，或输入'取消'放弃。"
        
        # 找到了目标歌曲
        filename = Path(target_song.file_path).name
        
        # 显示找到了哪首歌（特别是模糊匹配的情况）
        if file_hint and file_hint not in filename:
            print(f"💡 搜索 '{file_hint}' 找到: {target_song.artist} - {target_song.title}")
        
        # 如果不是从pending来的，先进行识别并让用户确认
        if not from_pending:
            print(f"🔍 正在识别: {filename}")
            
            # 使用 metadata_enhancer 搜索
            from agents.metadata_enhancer import MetadataEnhancer
            enhancer = MetadataEnhancer(kimi_client=self.librarian.kimi if self.librarian.has_llm else None)
            
            metadata = enhancer.search_by_filename(filename, download_cover=True)
            
            if not metadata or not metadata.get("title"):
                return f"❌ 未能识别歌曲信息: {filename}\n\n你可以：\n• 检查文件名是否包含歌手和歌名\n• 尝试手动修改文件名后重新扫描\n• 或使用批量修复功能'修复元数据'"
            
            # 保存识别结果到 pending action（同时保存 cover_url 以便确认后重新下载）
            self.context.set_pending(PendingAction(
                action_type="fix_single",
                params={
                    "song_id": target_song.id,
                    "title": metadata.get('title'),
                    "artist": metadata.get('artist'),
                    "album": metadata.get('album', ''),
                    "year": metadata.get('year', 0),
                    "genre": metadata.get('genre', ''),
                    "cover_path": metadata.get('cover_path'),
                    "cover_url": metadata.get('cover_url'),  # 保存URL以便重新下载
                    "source": metadata.get('source'),
                    "from_pending": True
                },
                description=f"修复单曲元数据: {metadata.get('artist')} - {metadata.get('title')}"
            ))
            
            # 显示对比
            has_cover_path = metadata.get('cover_path') is not None
            has_cover_url = metadata.get('cover_url') is not None
            
            if has_cover_path:
                cover_status = "✅ 已下载"
            elif has_cover_url:
                cover_status = "⏳ 将在确认后下载"
            else:
                cover_status = "❌ 无封面数据"
            
            comparison = f"""📀 识别结果对比:

文件名: {filename}

当前信息:
• 歌名: {target_song.title}
• 歌手: {target_song.artist}
• 专辑: {target_song.album or '未知'}
• 封面: {'✅ 有' if False else '❌ 无'}

新识别信息:
• 歌名: {metadata.get('title')}
• 歌手: {metadata.get('artist')}
• 专辑: {metadata.get('album', '未知')}
• 封面: {cover_status}
• 来源: {metadata.get('source', '未知')}"""
            
            # 检查是否一致
            is_different = (target_song.title != metadata.get('title') or 
                           target_song.artist != metadata.get('artist'))
            
            if is_different:
                comparison += "\n\n⚠️  注意：新识别信息与当前标签不一致！"
            
            comparison += "\n\n💡 确认后将同时写入元数据标签和专辑封面（如可用）"
            comparison += "\n输入'确认'执行，或'取消'放弃。"
            
            return comparison
        
        # 从 pending 来，执行实际写入（现在 song_id 查找已经在前面处理了）
        self.context.clear_pending()
        
        print(f"📝 正在写入: {target_song.artist} - {target_song.title}")
        
        # 更新歌曲对象
        target_song.title = params.get('title')
        target_song.artist = params.get('artist')
        if params.get('album'):
            target_song.album = params.get('album')
        if params.get('year'):
            target_song.year = params.get('year')
        if params.get('genre'):
            target_song.genre = params.get('genre')
        
        print(f"   新信息: {target_song.artist} - {target_song.title}")
        
        # 执行修复
        ext = Path(target_song.file_path).suffix.lower()
        if ext in ['.flac', '.mp3', '.m4a', '.mp4']:
            # 获取封面路径，如果没有但URL存在，尝试重新下载
            cover_path = params.get('cover_path')
            cover_url = params.get('cover_url')
            
            if not cover_path and cover_url:
                print(f"   [重新下载封面] ...")
                from agents.metadata_enhancer import MetadataEnhancer
                enhancer = MetadataEnhancer()
                cover_path = enhancer._download_cover(cover_url, target_song.album or target_song.title)
                if cover_path:
                    print(f"   [封面下载成功]")
                else:
                    print(f"   [封面下载失败]")
            
            has_cover = cover_path is not None
            
            if self.librarian._write_metadata_to_file(target_song, cover_path):
                result_lines = [
                    "✅ 元数据已成功写入！",
                    "",
                    f"• {target_song.artist} - {target_song.title}",
                    f"• 专辑: {target_song.album or '未知'}",
                ]
                
                if has_cover:
                    result_lines.append("🖼️ 专辑封面已嵌入")
                else:
                    result_lines.append("💡 未找到专辑封面（QQ音乐/网易云可能没有封面数据）")
                
                return "\n".join(result_lines)
            else:
                return "⚠️ 更新内存信息成功，但写入文件失败，请检查文件权限"
        else:
            return f"⚠️ 格式 {ext} 不支持写入标签，建议转换为 FLAC 格式\n输入'转换 wav 到 flac'进行转换"
    

    def handle_correct_language(self, params: Dict) -> str:
        """纠正语言"""
        from core.language_detector import detector
        import re
        
        text = params.get("input", "")
        
        # 匹配: "标记 BTS - Dynamite 为 韩语"
        match = re.search(r"(?:标记|纠正|设置语言)\s+(.+?)\s+(?:为|是|=)\s*(\S+)", text)
        if not match:
            return """格式错误！请使用:
  标记 BTS - Dynamite 为 韩语
  纠正 IU - Blueming 为 韩语"""
        
        song_info = match.group(1).strip()
        language = match.group(2).strip()
        
        # 解析
        if " - " in song_info:
            artist, title = song_info.rsplit(" - ", 1)
        else:
            return "格式错误！请使用 '艺术家 - 标题' 格式"
        
        detector.manual_set(artist.strip(), title.strip(), language)
        return f"✅ 已设置: {artist} - {title} = {language}"
    

    def handle_correct_emotion(self, params: Dict) -> str:
        """纠正情绪（命令式：标记/纠正 歌手 - 歌名 为 快乐/悲伤/...）"""
        import re
        from core.music_library_db import get_library_db
        from core.emotion_analyzer_simple import SimpleEmotionAnalyzer
        
        text = params.get("input", "")
        
        # 匹配: "标记 BTS - Dynamite 为 快乐" 或 "纠正晴天为悲伤"
        match = re.search(r"(?:标记|纠正)\s+(.+?)(?:的?情绪|的?心情|为|是|=)\s*(.+)", text)
        if not match:
            return """格式错误！请使用:
  标记 BTS - Dynamite 为 快乐
  纠正 周杰伦 - 晴天 的情绪为 悲伤"""
        
        song_info = match.group(1).strip()
        emotion_raw = match.group(2).strip()
        
        # 清理情绪值中的"的歌"等后缀
        for suffix in ["的歌", "歌"]:
            if emotion_raw.endswith(suffix):
                emotion_raw = emotion_raw[:-len(suffix)]
                break
        
        # 标准化情绪
        emotion_map = {
            "快乐": "happy", "开心": "happy", "欢快": "happy",
            "悲伤": "sad", "难过": "sad", "治愈": "sad", "安静": "sad", "抒情": "sad",
            "热血": "energetic", "激情": "energetic", "燃": "energetic",
            "平静": "calm", "放松": "calm", "舒缓": "calm",
            "浪漫": "romantic", "甜蜜": "romantic",
            "怀旧": "nostalgic", "经典": "nostalgic",
            "愤怒": "angry", "发泄": "angry",
            "专注": "focus", "工作": "focus",
            "派对": "party", "舞曲": "party",
        }
        emotion = emotion_map.get(emotion_raw, emotion_raw)
        
        # 查找匹配的歌曲
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        matched = []
        hint_lower = song_info.lower()
        
        # 尝试解析 "歌手 - 歌名" 格式
        if " - " in song_info:
            artist_hint, title_hint = song_info.rsplit(" - ", 1)
            artist_hint = artist_hint.strip().lower()
            title_hint = title_hint.strip().lower()
            for song in self.librarian.songs.values():
                if artist_hint in song.artist.lower() and title_hint in song.title.lower():
                    matched.append(song)
        else:
            # 模糊匹配标题或文件名
            for song in self.librarian.songs.values():
                if hint_lower in song.title.lower() or hint_lower in Path(song.file_path).stem.lower():
                    matched.append(song)
        
        if not matched:
            return f"❌ 未找到包含 '{song_info}' 的歌曲\n提示：使用 '歌手 - 歌名' 格式更精确"
        
        if len(matched) > 1:
            songs_list = "\n".join([f"  {i+1}. {s.artist} - {s.title}" for i, s in enumerate(matched[:5])])
            return f"找到多首匹配歌曲：\n{songs_list}\n\n请使用更精确的 '歌手 - 歌名' 格式"
        
        song = matched[0]
        analyzer = SimpleEmotionAnalyzer()
        analyzer.manual_set(song.file_path, emotion)
        
        lib_db = get_library_db()
        lib_db.update_emotion(song.artist, song.title, emotion, '1.0')
        
        emotion_names = {
            'happy': '快乐', 'sad': '悲伤', 'energetic': '激情',
            'calm': '平静', 'romantic': '浪漫', 'nostalgic': '怀旧',
            'angry': '愤怒', 'focus': '专注', 'party': '派对'
        }
        display = emotion_names.get(emotion, emotion)
        return f"✅ 已纠正情绪: {song.artist} - {song.title} = {display}"
    

    def handle_update_song_info(self, params: Dict) -> str:
        """自然语言方式更新歌曲信息（如'supernatural是韩语歌'、'kanye west的歌全都是英文的'）"""
        from core.music_library_db import get_library_db
        from core.language_detector import detector
        
        song_hint = params.get("song_hint", "")
        field = params.get("field", "")
        value = params.get("value", "")
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        # 保存原始 hint 用于判断批量意图
        original_hint = song_hint
        
        # 清理批量词后缀（如 "kanye west的歌全都" → "kanye west"）
        batch_suffixes = ["的歌全都", "的歌全部", "的歌所有", "的都", "的歌", "全都", "全部", "所有"]
        has_batch_suffix = False
        for suffix in batch_suffixes:
            if song_hint.endswith(suffix):
                song_hint = song_hint[:-len(suffix)].strip()
                has_batch_suffix = True
                break
        
        # 查找匹配的歌曲
        matched_songs = []
        hint_lower = song_hint.lower()
        
        for song in self.librarian.songs.values():
            # 匹配标题或文件名
            title_match = hint_lower in song.title.lower()
            file_match = hint_lower in Path(song.file_path).stem.lower()
            # 也尝试匹配 歌手 - 歌名 格式
            full_match = hint_lower in f"{song.artist} - {song.title}".lower()
            
            if title_match or file_match or full_match:
                matched_songs.append(song)
        
        # 如果没找到，尝试用 hint 作为 artist 名模糊匹配
        if not matched_songs:
            artist_matched = []
            for song in self.librarian.songs.values():
                if song_hint.lower() in song.artist.lower() or song.artist.lower() in song_hint.lower():
                    artist_matched.append(song)
            if artist_matched:
                matched_songs = artist_matched
                has_batch_suffix = True  # 按 artist 匹配视为批量意图
            else:
                return f"❌ 未找到包含 '{original_hint}' 的歌曲\n\n提示：你可以说 '标记 歌手 - 歌名 为 {value}' 来精确指定"
        
        # 判断是否批量：有批量后缀，或所有匹配歌曲属于同一歌手且数量较多
        same_artist = len(set(s.artist for s in matched_songs)) == 1
        is_batch = has_batch_suffix or (same_artist and len(matched_songs) > 1)
        
        if len(matched_songs) > 1 and not is_batch:
            # 多首不同歌手，显示列表
            songs_list = "\n".join([f"  {i+1}. {s.artist} - {s.title}" for i, s in enumerate(matched_songs[:10])])
            return f"找到多首匹配歌曲：\n{songs_list}\n\n请使用更精确的歌名，或者说：\n标记 歌手 - 歌名 为 {value}"
        
        song = matched_songs[0]
        lib_db = get_library_db()
        
        # 标准化值
        if field == "language":
            # 统一语言名称
            lang_map = {
                "韩文": "韩语", "韩": "韩语", "korean": "韩语", "kr": "韩语",
                "日文": "日语", "日": "日语", "japanese": "日语", "jp": "日语",
                "英文": "英语", "英": "英语", "english": "英语", "en": "英语",
                "中文": "国语", "普通话": "国语", "国语": "国语", "mandarin": "国语",
                "粤语": "粤语", "广东话": "粤语", "cantonese": "粤语",
            }
            normalized_value = lang_map.get(value.lower(), value)
            
            # 批量更新模式
            if is_batch and len(matched_songs) > 1:
                updated = 0
                artist_name = matched_songs[0].artist
                for s in matched_songs:
                    detector.manual_set(s.artist, s.title, normalized_value)
                    lib_db.update_language(s.artist, s.title, normalized_value, 'manual')
                    updated += 1
                return f"✅ 已批量设置 {artist_name} 的 {updated} 首歌曲为 {normalized_value}"
            
            # 单首更新
            detector.manual_set(song.artist, song.title, normalized_value)
            
            # 更新音乐库数据库（SQLite 即时写入）
            lib_db.update_language(song.artist, song.title, normalized_value, 'manual')
            
            return f"✅ 已设置语言: {song.artist} - {song.title} = {normalized_value}"
        
        elif field == "emotion":
            # 标准化情绪名称
            emotion_map = {
                "快乐": "happy", "开心": "happy", "欢快": "happy",
                "悲伤": "sad", "难过": "sad", "治愈": "sad", "安静": "sad", "抒情": "sad",
                "热血": "energetic", "激情": "energetic", "燃": "energetic",
                "平静": "calm", "放松": "calm", "舒缓": "calm",
                "浪漫": "romantic", "甜蜜": "romantic",
                "怀旧": "nostalgic", "经典": "nostalgic",
                "愤怒": "angry", "发泄": "angry",
                "专注": "focus", "工作": "focus",
                "派对": "party", "舞曲": "party",
            }
            normalized_value = emotion_map.get(value, value)
            
            # 批量更新模式
            if is_batch and len(matched_songs) > 1:
                from core.emotion_analyzer_simple import SimpleEmotionAnalyzer
                analyzer = SimpleEmotionAnalyzer()
                updated = 0
                artist_name = matched_songs[0].artist
                for s in matched_songs:
                    analyzer.manual_set(s.file_path, normalized_value)
                    lib_db.update_emotion(s.artist, s.title, normalized_value, '1.0')
                    updated += 1
                return f"✅ 已批量设置 {artist_name} 的 {updated} 首歌曲情绪为 {normalized_value}"
            
            # 单首更新：同步写入 emotion_cache（确保 _filter_by_mood 能读到）
            from core.emotion_analyzer_simple import SimpleEmotionAnalyzer
            analyzer = SimpleEmotionAnalyzer()
            analyzer.manual_set(song.file_path, normalized_value)
            
            # 更新音乐库数据库（SQLite 即时写入）
            lib_db.update_emotion(song.artist, song.title, normalized_value, '1.0')
            
            emotion_names = {
                'happy': '快乐', 'sad': '悲伤', 'energetic': '激情',
                'calm': '平静', 'romantic': '浪漫', 'nostalgic': '怀旧',
                'angry': '愤怒', 'focus': '专注', 'party': '派对'
            }
            display_emotion = emotion_names.get(normalized_value, normalized_value)
            
            return f"✅ 已设置情绪: {song.artist} - {song.title} = {display_emotion}"
        
        return f"❌ 未知字段: {field}"
    
    def _clean_play_name(self, name: str) -> str:
        """清洗歌名：去除书名号、歌手名后缀/前缀、通用后缀如'的歌'"""
        import re
        name = name.strip()
        # 去除书名号《》
        if name.startswith("《") and name.endswith("》"):
            name = name[1:-1]
        # 去除尾部 " - 歌手名" 如 "程艾影 - 赵雷"
        name = re.sub(r'\s*[-–—]\s*\S+\s*$', '', name)
        # 去除头部 "歌手名 - " 如 "赵雷 - 程艾影"
        name = re.sub(r'^\S+\s*[-–—]\s*', '', name)
        # 去除通用后缀："的歌"、"这首歌"、"的歌曲"
        for suffix in ["的歌曲", "这首歌", "的歌"]:
            if name.endswith(suffix):
                name = name[:-len(suffix)]
                break
        return name.strip()


    def handle_diagnose(self, params: Dict) -> str:
        """Diagnose metadata completeness across the library."""
        if not self.librarian.songs:
            self.librarian.run("scan")

        issues = self.librarian.diagnose_metadata()
        total = len(self.librarian.songs)
        missing_artist = issues.get("missing_artist", 0)
        missing_album = issues.get("missing_album", 0)
        missing_genre = issues.get("missing_genre", 0)
        missing_cover = issues.get("missing_cover", 0)
        missing_language = issues.get("missing_language", 0)
        missing_emotion = issues.get("missing_emotion", 0)

        lines = [f"📊 元数据诊断报告（共 {total} 首歌曲）：", ""]
        lines.append(f"• 缺少歌手: {missing_artist} 首")
        lines.append(f"• 缺少专辑: {missing_album} 首")
        lines.append(f"• 缺少流派: {missing_genre} 首")
        lines.append(f"• 缺少封面: {missing_cover} 首")
        lines.append(f"• 缺少语言标签: {missing_language} 首")
        lines.append(f"• 缺少情绪标签: {missing_emotion} 首")

        if any([missing_artist, missing_album, missing_genre, missing_cover, missing_language, missing_emotion]):
            lines.append("")
            lines.append("💡 输入「一键修复」来自动补全元数据")
        else:
            lines.append("")
            lines.append("✅ 所有歌曲元数据完整！")

        return "\n".join(lines)

    def handle_fix_metadata_issues(self, params: Dict) -> str:
        """One-click batch metadata fix."""
        if not self.librarian.songs:
            self.librarian.run("scan")

        print("正在修复元数据...")
        result = self.librarian.fix_metadata(dry_run=False, rename_files=False, download_cover=True)
        processed = result.get("processed", 0)
        fixed = result.get("fixed", 0)
        written = result.get("written", 0)

        return f"✅ 元数据修复完成！处理 {processed} 首，识别 {fixed} 首，写入标签 {written} 首。"

    def handle_sync_emotion(self, params: Dict) -> str:
        """Sync emotion cache to database."""
        print("正在同步情绪缓存到数据库...")
        count = self.librarian.sync_emotion_cache()
        return f"✅ 情绪缓存已同步，更新 {count} 首歌曲。"

