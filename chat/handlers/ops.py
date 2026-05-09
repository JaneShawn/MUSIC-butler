# -*- coding: utf-8 -*-
"""OpsHandlers - handler mixin for MusicAgentChat."""
from typing import Dict, Any
class OpsHandlers:
    """Handler methods mixed into MusicAgentChat."""

    def handle_scan(self, params: Dict) -> str:
        print("正在扫描音乐库...")
        result = self.librarian.run("scan")
        return f"扫描完成！发现 {result['total_files']} 个文件，索引 {result['total_indexed']} 首歌曲。"
    

    def handle_organize(self, params: Dict) -> str:
        strategy = params.get("strategy", "artist/album")
        from_pending = params.get("from_pending", False)
        
        if not from_pending:
            print(f"正在规划整理方案 ({strategy})...")
            plan = self.organizer.run("plan", strategy=OrganizeStrategy(strategy))
            preview = self.organizer.preview_plan(plan)["summary"]
            
            self.context.set_pending(PendingAction(
                action_type="organize",
                params={"strategy": strategy, "from_pending": True},
                description=f"按{strategy}整理音乐文件"
            ))
            
            return f"""整理计划预览：
• 总文件: {preview['total_files']} 首
• 将移动: {preview['to_move']} 首
• 将复制: {preview['to_copy']} 首
• 跳过: {preview['skip']} 首
• 冲突: {preview['conflicts']} 首

输入'确认'执行，或'取消'放弃。"""
        
        print("正在执行整理...")
        plan = self.organizer.run("plan", strategy=OrganizeStrategy(strategy))
        result = self.organizer.run("execute", plan=plan, dry_run=False)
        self.context.clear_pending()
        return f"整理完成！成功: {result.executed} 首, 失败: {result.failed} 首"
    

    def handle_dedup(self, params: Dict) -> str:
        """处理重复歌曲"""
        confirm = params.get("confirm", False)
        from_pending = params.get("from_pending", False)
        
        from agents.organizer import OrganizeStrategy
        
        if not from_pending:
            print("🔍 正在分析重复歌曲...")
            plan = self.organizer.run("plan", strategy=OrganizeStrategy.REMOVE_DUPLICATES)
            
            if not plan:
                return "✅ 没有发现重复歌曲！"
            
            dup_plans = [p for p in plan if p.action == "move"]
            keep_plans = [p for p in plan if p.action == "skip" and "重复" in p.reason]
            
            if not dup_plans:
                return "✅ 没有发现重复歌曲！"
            
            preview_text = ""
            shown = 0
            for p in keep_plans[:5]:
                match = p.reason.split("发现 ")[1].split(" 个")[0] if "发现 " in p.reason else "?"
                preview_text += f"\n  • 《{p.song.title}》- {p.song.artist} ({match}个重复)"
                shown += 1
            
            self.context.set_pending(PendingAction(
                action_type="dedup",
                params={"confirm": True, "from_pending": True},
                description=f"清理 {len(dup_plans)} 首重复歌曲"
            ))
            
            more_text = f"\n  ... 还有 {len(keep_plans) - shown} 组" if len(keep_plans) > shown else ""
            
            return f"""📊 重复检测结果：
• 重复组数: {len(keep_plans)} 组
• 重复文件: {len(dup_plans)} 首
• 保留文件: {len(keep_plans)} 首

重复示例:{preview_text}{more_text}

💡 重复文件将被移动到 _duplicates 文件夹（不会删除）

输入'确认'执行去重。"""
        
        print("\n🚀 正在执行去重...")
        plan = self.organizer.run("plan", strategy=OrganizeStrategy.REMOVE_DUPLICATES)
        result = self.organizer.run("execute", plan=plan, dry_run=False)
        self.context.clear_pending()
        
        return f"""✅ 去重完成！
• 已移动: {result.executed} 首重复文件到 _duplicates 文件夹
• 已保留: {len(plan) - result.executed} 首最佳版本
• 失败: {result.failed} 首

💡 重复文件保存在: MUSIC/_duplicates/
你可以手动检查并删除这些文件。"""
    

    def handle_convert(self, params: Dict) -> str:
        """处理音频格式转换（WAV 转 FLAC）"""
        output_format = params.get("format", "flac")
        delete_source = params.get("delete_source", False)
        confirm = params.get("confirm", False)
        from_pending = params.get("from_pending", False)
        
        # 初始化转换器
        converter = AudioConverter()
        
        # 检查 ffmpeg
        if not converter.check_ffmpeg():
            return converter.get_ffmpeg_install_help()
        
        library_path = self.config.get("library", {}).get("path", ".")
        
        if not from_pending:
            # 预览模式
            print("🔍 扫描可转换的音频文件...")
            preview = preview_conversion(library_path)
            
            if not preview['convertible']:
                return "✅ 没有发现需要转换的文件（没有 WAV/AIFF 格式文件）"
            
            files = preview['convertible']
            file_list = "\n".join([f"  • {Path(f['source']).name} ({f['size_mb']}MB)" for f in files[:5]])
            more = f"\n  ... 还有 {len(files) - 5} 个文件" if len(files) > 5 else ""
            
            # 设置待执行操作
            self.context.set_pending(PendingAction(
                action_type="convert",
                params={
                    "format": output_format,
                    "delete_source": delete_source,
                    "confirm": True,
                    "from_pending": True
                },
                description=f"将 {len(files)} 个文件转换为 {output_format.upper()}{' 并删除源文件' if delete_source else ''}"
            ))
            
            delete_hint = "\n⚠️  注意：转换后将删除原始 WAV 文件" if delete_source else ""
            
            return f"""🎵 音频格式转换预览

可转换文件: {len(files)} 个
总大小: {preview['total_size_mb']} MB
预计转换后: ~{round(preview['total_size_mb'] * 0.6)} MB (FLAC 压缩)
预计节省: {preview['estimated_savings_mb']} MB

示例文件:
{file_list}{more}{delete_hint}

转换好处：
• 节省磁盘空间（FLAC 比 WAV 小 30-50%）
• 支持完整的元数据标签
• 支持专辑封面嵌入
• 音质完全无损

输入'确认转换'执行，或'取消'放弃。"""
        
        # 执行转换
        print("\n🚀 开始转换...")
        
        # 扫描文件
        files = converter.scan_convertible_files(library_path)
        tasks = converter.generate_conversion_plan(files, f".{output_format}")
        
        if not tasks:
            self.context.clear_pending()
            return "❌ 没有找到可转换的文件"
        
        # 执行批量转换
        total = len(tasks)
        success = 0
        failed = 0
        
        print(f"共 {total} 个文件需要转换\n")
        
        for i, task in enumerate(tasks, 1):
            print(f"[{i}/{total}] {Path(task.source_path).name}...", end=" ", flush=True)
            
            if converter.convert_file(task):
                print("✅")
                success += 1
            else:
                print(f"❌ {task.error}")
                failed += 1
        
        # 如果需要，删除源文件
        delete_result = None
        if delete_source and success > 0:
            print(f"\n🗑️  正在删除源文件...")
            delete_result = converter.delete_source_files(tasks, dry_run=False)
        
        self.context.clear_pending()
        
        # 构建结果消息
        result_msg = f"""✅ 转换完成！
• 总计: {total} 个文件
• 成功: {success} 个
• 失败: {failed} 个"""
        
        if delete_result:
            result_msg += f"\n• 已删除源文件: {delete_result['deleted']} 个"
            if delete_result['errors'] > 0:
                result_msg += f"\n• 删除失败: {delete_result['errors']} 个"
        
        result_msg += """\n\n💡 提示：
转换后的 FLAC 文件已保存在原目录。
建议运行'修复元数据'补全歌曲信息。"""
        
        return result_msg
    

    def handle_delete_wav(self, params: Dict) -> str:
        """直接删除 WAV 文件（不转换）"""
        confirm = params.get("confirm", False)
        from_pending = params.get("from_pending", False)
        
        library_path = self.config.get("library", {}).get("path", ".")
        
        # 扫描 WAV 文件
        from core.audio_converter import AudioConverter
        converter = AudioConverter()
        wav_files = converter.scan_convertible_files(library_path)
        
        if not wav_files:
            return "✅ 没有发现 WAV 文件"
        
        if not from_pending:
            # 预览模式
            total_size = sum(Path(f).stat().st_size for f in wav_files)
            file_list = "\n".join([f"  • {Path(f).name}" for f in wav_files[:5]])
            more = f"\n  ... 还有 {len(wav_files) - 5} 个文件" if len(wav_files) > 5 else ""
            
            self.context.set_pending(PendingAction(
                action_type="delete_wav",
                params={"confirm": True, "from_pending": True},
                description=f"删除 {len(wav_files)} 个 WAV 文件（释放 {round(total_size/1024/1024)} MB 空间）"
            ))
            
            return f"""🗑️ 删除 WAV 文件预览

发现 WAV 文件: {len(wav_files)} 个
总大小: {round(total_size/1024/1024)} MB

文件列表:
{file_list}{more}

⚠️  警告：此操作将永久删除文件，无法恢复！
如果文件中有珍贵的音乐，建议先转换为 FLAC 格式。

输入'确认删除'执行删除，或'取消'放弃。
输入'转换 wav 到 flac'可先转换再删除。"""
        
        # 执行删除
        print(f"\n🗑️  正在删除 {len(wav_files)} 个 WAV 文件...")
        deleted = 0
        failed = 0
        errors = []
        
        for i, file_path in enumerate(wav_files, 1):
            print(f"  [{i}/{len(wav_files)}] {Path(file_path).name}...", end=" ")
            try:
                Path(file_path).unlink()
                print("已删除")
                deleted += 1
            except Exception as e:
                print(f"失败: {e}")
                failed += 1
                errors.append(f"{Path(file_path).name}: {e}")
        
        self.context.clear_pending()
        
        result = f"""✅ 删除完成！
• 总计: {len(wav_files)} 个文件
• 已删除: {deleted} 个
• 失败: {failed} 个"""
        
        if errors and failed > 0:
            result += f"\n\n错误详情:\n" + "\n".join(errors[:3])
        
        return result
    

    def handle_download_lyrics(self, params: Dict) -> str:
        """批量下载歌词文件到专用目录 (data/lyrics/)"""
        from core.lyrics_fetcher import LyricsFetcher
        from pathlib import Path
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        total = len(self.librarian.songs)
        if total == 0:
            return "音乐库为空"
        
        print(f"准备为 {total} 首歌曲下载歌词...")
        print("歌词将保存到: data/lyrics/")
        print("(使用网易云API，可能需要几分钟)\n")
        
        fetcher = LyricsFetcher(lyrics_dir="data/lyrics")
        
        # 准备歌曲列表
        songs_data = []
        for song in self.librarian.songs.values():
            songs_data.append({
                'file_path': song.file_path,
                'title': song.title,
                'artist': song.artist
            })
        
        # 批量获取歌词
        downloaded = 0
        failed = 0
        skipped = 0
        
        for i, song in enumerate(songs_data, 1):
            file_path = song['file_path']
            title = song['title']
            artist = song['artist']
            
            # 检查专用歌词目录是否已有
            if fetcher._from_lyrics_dir(title, artist):
                skipped += 1
                continue
            
            # 获取歌词
            try:
                lyrics = fetcher.fetch(title, artist, file_path)
                if lyrics:
                    # 保存到专用歌词目录
                    if fetcher.save_to_lyrics_dir(title, artist, lyrics):
                        downloaded += 1
                        print(f"✓ {title} - {artist}")
                    else:
                        failed += 1
                        print(f"✗ {title} - 保存失败")
                else:
                    failed += 1
                    print(f"✗ {title} - 未找到歌词")
            except Exception as e:
                failed += 1
                print(f"✗ {title} - 错误: {e}")
            
            if i % 20 == 0:
                print(f"\n进度: {i}/{total} (成功:{downloaded} 失败:{failed} 跳过:{skipped})\n")
        
        return f"""歌词下载完成！

📊 统计：
• 总歌曲: {total} 首
• 下载成功: {downloaded} 首
• 已存在跳过: {skipped} 首  
• 未找到: {failed} 首

💾 歌词文件 (.lrc) 保存位置: data/lyrics/
✅ 下次情绪分析将自动使用这些歌词，无需重新下载
💡 可用 foobar2000 等播放器显示歌词（需配置歌词路径）
"""
    
    def _recognize_single_song(self, song, generator, fetcher) -> str:
        """识别单首歌曲的歌词"""
        from core.lyrics_generator import LyricsGenerator
        
        print(f"\n🎵 识别歌曲: {song.artist} - {song.title}")
        print("🤖 使用模型: Whisper large (约1.5GB，准确率最高)")
        print("📄 输出格式: 标准LRC (带精确时间戳)")
        print("⏳ 识别中，请稍候...\n")
        
        try:
            lyrics = generator.generate(song.file_path, method="whisper")
            if lyrics:
                # 保存
                if generator.save_lyrics(song.file_path, lyrics):
                    # 显示前10行
                    preview_lines = lyrics.split('\n')[:12]
                    preview = '\n'.join(preview_lines)
                    return f"""
🎤 AI歌词识别成功！

📍 歌曲: {song.artist} - {song.title}
💾 保存路径: data/lyrics/{song.artist} - {song.title}.lrc

📝 歌词预览:
```
{preview}
...
```
"""
                else:
                    return "识别成功但保存失败"
            else:
                return "❌ 识别失败（可能是纯音乐或音频不清晰）"
        except Exception as e:
            return f"❌ 识别错误: {e}"


    def handle_generate_lyrics_whisper(self, params: Dict) -> str:
        """使用Whisper AI识别未找到歌词的歌曲"""
        from core.lyrics_generator import LyricsGenerator, install_whisper_hint
        from core.lyrics_fetcher import LyricsFetcher
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        total = len(self.librarian.songs)
        if total == 0:
            return "音乐库为空"
        
        # 初始化生成器
        generator = LyricsGenerator()
        fetcher = LyricsFetcher(lyrics_dir="data/lyrics")
        
        if not generator.whisper_available:
            install_whisper_hint()
            return "请先安装Whisper: pip install openai-whisper"
        
        # 检查是否指定了特定歌曲
        target_song_name = params.get("song_name", "")
        if target_song_name:
            # 查找匹配的歌曲
            matched_songs = []
            for song in self.librarian.songs.values():
                if target_song_name.lower() in song.title.lower() or \
                   target_song_name.lower() in f"{song.artist} - {song.title}".lower():
                    matched_songs.append(song)
            
            if matched_songs:
                print(f"找到 {len(matched_songs)} 首匹配歌曲")
                # 只处理第一首匹配的
                song = matched_songs[0]
                return self._recognize_single_song(song, generator, fetcher)
            else:
                return f"未找到包含 '{target_song_name}' 的歌曲"
        
        # 找出没有歌词的歌曲
        print("正在检查哪些歌曲需要识别歌词...")
        songs_without_lyrics = []
        
        for song in self.librarian.songs.values():
            # 检查专用歌词目录
            if not fetcher._from_lyrics_dir(song.title, song.artist):
                # 检查网易云是否有
                if not fetcher.fetch(song.title, song.artist, song.file_path):
                    songs_without_lyrics.append({
                        'file_path': song.file_path,
                        'title': song.title,
                        'artist': song.artist
                    })
        
        if not songs_without_lyrics:
            return "所有歌曲都已有歌词！"
        
        print(f"\n找到 {len(songs_without_lyrics)} 首没有歌词的歌曲")
        print("将使用AI语音识别生成歌词...")
        print("🤖 使用模型: Whisper large (约1.5GB，准确率最高)")
        print("📄 输出格式: 标准LRC (带精确时间戳)")
        print("⚠️ 注意：首次使用需下载模型，识别速度较慢\n")
        
        # 限制数量（避免太长）
        to_process = songs_without_lyrics[:20]  # 最多处理20首
        
        recognized = 0
        failed = 0
        
        for i, song in enumerate(to_process, 1):
            print(f"\n[{i}/{len(to_process)}] 识别: {song['title']} - {song['artist']}")
            
            try:
                lyrics = generator.generate(song['file_path'], method="whisper")
                if lyrics:
                    # 保存
                    if generator.save_lyrics(song['file_path'], lyrics):
                        recognized += 1
                        print(f"  ✓ 识别成功，保存到 data/lyrics/")
                    else:
                        failed += 1
                        print(f"  ✗ 保存失败")
                else:
                    failed += 1
                    print(f"  ✗ 识别失败（可能是纯音乐或无法识别）")
            except Exception as e:
                failed += 1
                print(f"  ✗ 错误: {e}")
        
        return f"""
🎤 AI歌词识别完成！

📊 统计：
• 需要识别的歌曲: {len(songs_without_lyrics)} 首
• 本次处理: {len(to_process)} 首（限制20首）
• 识别成功: {recognized} 首
• 识别失败: {failed} 首

💡 识别的歌词已保存到 data/lyrics/
💡 建议检查识别结果，AI可能有错误
💡 剩余 {len(songs_without_lyrics) - len(to_process)} 首可再次运行此命令

使用方法:
    1. 安装Whisper: pip install openai-whisper
    2. 确保已安装ffmpeg
    3. 重新运行"识别歌词"
"""


    def handle_monitor(self, params: Dict) -> str:
        """Control folder monitoring: start, stop, or check status."""
        action = params.get("action", "status")
        fw = self.folder_watcher
        if action == "start":
            if fw.is_running:
                return "实时监控已在运行中。"
            fw.start()
            if fw.is_running:
                dirs = ", ".join(fw.get_watched_dirs())
                return f"✅ 实时监控已启动！\n📁 监控目录: {dirs}"
            return "⚠️ 监控启动失败，请检查配置。"
        elif action == "stop":
            if not fw.is_running:
                return "实时监控未在运行。"
            fw.stop()
            return "✅ 实时监控已关闭。"
        else:
            if fw.is_running:
                dirs = ", ".join(fw.get_watched_dirs())
                return f"🟢 实时监控运行中\n📁 监控目录: {dirs}"
            return "🔴 实时监控未运行。输入「开启监控」启动。"

