# -*- coding: utf-8 -*-
"""ManageHandlers - handler mixin for MusicAgentChat."""
from typing import Dict, Any
class ManageHandlers:
    """Handler methods mixed into MusicAgentChat."""

    def handle_list_models(self, params: Dict) -> str:
        """列出可用的Embedding模型"""
        from core.vector_store import _check_sentence_transformers
        
        has_st = _check_sentence_transformers()
        
        lines = ["📋 可用Embedding模型：\n"]
        
        if not has_st:
            lines.append("⚠️  sentence-transformers 未安装，当前使用ChromaDB默认embedding")
            lines.append("    查询功能可用，但中文语义理解效果可能稍差\n")
            lines.append("💡 如需高质量中文检索，请安装：")
            lines.append("   pip install sentence-transformers\n")
        
        lines.append(f"{'别名':<20} {'模型名称':<45} {'状态'}")
        lines.append("-" * 80)
        
        current = self.config.get("rag", {}).get("embedding_model", "bge-small-zh")
        
        descriptions = {
            "bge-small-zh": "中文轻量，速度快，推荐" if has_st else "需安装 sentence-transformers",
            "bge-large-zh": "中文高精度，质量更好" if has_st else "需安装 sentence-transformers",
            "bge-base-zh": "平衡选择" if has_st else "需安装 sentence-transformers",
            "paraphrase-multilingual": "多语言支持" if has_st else "需安装 sentence-transformers",
            "all-MiniLM": "英文轻量（不推荐中文）" if has_st else "需安装 sentence-transformers",
        }
        
        for alias, model_name in EMBEDDING_MODELS.items():
            status = "✓ 当前使用" if alias == current else ""
            if not has_st:
                status = "✗ 需安装依赖"
            desc = descriptions.get(alias, "")
            lines.append(f"{alias:<20} {model_name:<45} {status}")
            if desc:
                lines.append(f"  └─ {desc}")
        
        if has_st:
            lines.append(f"\n💡 使用方式：输入'切换模型 bge-large-zh'")
        else:
            lines.append(f"\n⚠️  当前使用ChromaDB内置embedding，无需切换")
            lines.append("   安装 sentence-transformers 后可使用高质量中文模型")
        
        return "\n".join(lines)
    

    def handle_switch_model(self, params: Dict) -> str:
        """切换Embedding模型"""
        from core.vector_store import _check_sentence_transformers
        
        # 检查是否安装了 sentence-transformers
        if not _check_sentence_transformers():
            return """❌ 无法切换模型

sentence-transformers 未安装，当前使用ChromaDB默认embedding。

如需使用高质量中文模型，请安装：
   pip install sentence-transformers

安装后可使用：
   • bge-small-zh (推荐) - 中文轻量，速度快
   • bge-large-zh - 中文高精度，质量更好
   • bge-base-zh - 平衡选择

当前状态：使用ChromaDB默认embedding（无需额外安装，查询功能正常）"""
        
        model_alias = params.get("model", "bge-small-zh")
        
        if model_alias not in EMBEDDING_MODELS:
            return f"❌ 未知模型: {model_alias}\n可用模型: {', '.join(EMBEDDING_MODELS.keys())}"
        
        # 更新配置
        self.config["rag"]["embedding_model"] = model_alias
        
        # 保存到配置文件
        try:
            config_path = Path(__file__).parent / "config.yaml"
            with open(config_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # 替换配置中的模型名称
            import re
            content = re.sub(
                r'(embedding_model:\s*)"[^"]+"',
                f'\\1"{model_alias}"',
                content
            )
            
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(content)
            
            return f"""✅ 已切换到模型: {model_alias}
📦 {EMBEDDING_MODELS[model_alias]}

⚠️  重要：更换模型后需要重建向量数据库
请按以下步骤操作：
1. 退出当前会话
2. 运行: python tools_manage_embedding.py reset
3. 重新运行本程序，输入'扫描'重建索引

原因：不同模型生成的向量不兼容，必须重新计算"""
            
        except Exception as e:
            return f"❌ 保存配置失败: {e}\n但当前会话已切换，重启后失效。"
    

    def handle_current_model(self, params: Dict) -> str:
        """显示当前使用的模型"""
        from core.vector_store import _check_sentence_transformers
        
        has_st = _check_sentence_transformers()
        
        # 获取向量库统计
        stats = self.librarian.vector_store.get_stats()
        
        if not has_st:
            return f"""📊 当前Embedding配置：
• 模式: ChromaDB默认embedding
• 状态: ⚠️ sentence-transformers 未安装
• 已索引歌曲: {stats.get('document_count', 0)} 首

💡 说明：
当前使用ChromaDB内置的embedding算法，无需额外安装依赖。
查询功能完全可用，但中文语义理解效果可能不如专用模型。

如需高质量中文检索，请安装：
   pip install sentence-transformers

安装后可使用 bge-small-zh 等中文优化模型。"""
        
        current = self.config.get("rag", {}).get("embedding_model", "bge-small-zh")
        model_full = EMBEDDING_MODELS.get(current, current)
        
        return f"""📊 当前Embedding配置：
• 模型别名: {current}
• 模型全称: {model_full}
• 运行设备: {stats.get('device', 'cpu')}
• 向量维度: 根据模型而定（约384-1024维）
• 已索引歌曲: {stats.get('document_count', 0)} 首

💡 要切换模型，输入: 切换模型 bge-large-zh"""
    

    def handle_export_library(self, params: Dict) -> str:
        """导出完整音乐库文档"""
        from core.music_library_db import get_library_db
        
        if not self.librarian.songs:
            return "请先扫描音乐库"
        
        print("正在生成音乐库文档...")
        
        # 先更新所有歌曲到数据库
        lib_db = get_library_db()
        for song in self.librarian.songs.values():
            # 如果数据库中没有，添加基础信息
            if not lib_db.get_record(song.artist, song.title):
                lib_db.update_or_create(
                    file_path=song.file_path,
                    title=song.title,
                    artist=song.artist,
                    album=song.album,
                    genre=song.genre,
                    year=str(song.year) if song.year else "",
                    duration=str(song.duration) if song.duration else ""
                )
        
        # 导出CSV
        csv_path = lib_db.export_to_csv()
        
        if not csv_path:
            return "导出失败，请检查日志"
        
        stats = lib_db.get_stats()
        
        return f"""
✅ 音乐库文档已生成！

📁 文件位置: {csv_path}

📊 音乐库概况:
  • 总歌曲: {stats['total']} 首
  • 已识别语言: {len(stats['languages'])} 种
  • 有歌词: {stats['lyrics_count']} 首

📝 可编辑字段:
  • 语言（英语/国语/粤语/日语/韩语）
  • 情绪（快乐/悲伤/平静等）
  • 用户备注（自由填写）
  • 播放次数

💡 使用方法:
  1. 用Excel打开 CSV 文件
  2. 修改想调整的字段
  3. 保存后输入: 导入文档
  4. 或者直接输入: 导入音乐库

📌 文档会自动更新，每次扫描后都可用 导出文档 获取最新版本
"""
    

    def handle_import_library(self, params: Dict) -> str:
        """导入音乐库文档"""
        from core.music_library_db import get_library_db
        
        lib_db = get_library_db()
        updated = lib_db.import_from_csv()
        
        if updated > 0:
            return f"""
✅ 成功导入 {updated} 条修改！

📊 更新后的音乐库:
  • 总记录: {len(lib_db.records)} 首

💡 现在可以用以下命令查询:
  • 有哪些韩语歌
  • 有哪些快乐的歌
  • 导出文档 - 查看完整表格
"""
        else:
            return """
⚠️ 没有需要导入的修改

💡 请先用Excel编辑导出的文档，再执行导入
步骤:
  1. 导出文档
  2. Excel编辑
  3. 保存CSV
  4. 导入文档
"""
    

    def handle_export_language_csv(self, params: Dict) -> str:
        """导出语言到CSV"""
        from core.language_detector import detector
        import csv
        from datetime import datetime
        
        if not self.librarian.songs:
            return "请先扫描音乐库"
        
        # 确保所有歌曲都有检测结果
        for song in self.librarian.songs.values():
            detector.detect(song.title, song.artist, song.file_path)
        
        # 导出CSV
        csv_path = Path("data/songs_language.csv")
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['artist', 'title', 'language', 'source', 'confidence', 'notes'])
            for key, item in detector.cache.items():
                writer.writerow([
                    item['artist'], item['title'], item['language'],
                    item['source'], item['confidence'], ''
                ])
        
        return f"""
✅ 已导出到: {csv_path}

📊 {len(detector.cache)} 首歌曲

📝 编辑方法:
1. 用Excel打开
2. 修改 language 列
3. 保存后对我说：导入语言

💡 或者直接说:
   标记 BTS - Dynamite 为 韩语
"""
    

    def handle_playlist(self, params: Dict) -> str:
        """创建 foobar2000 格式的播放列表"""
        from core.playlist_manager import PlaylistGenerator
        
        if not self.librarian.songs:
            self.librarian.run("scan")
        
        if not self.librarian.songs:
            return "音乐库为空，请先添加歌曲。"
        
        mode = params.get("mode", "shuffle")
        query = params.get("query", "")
        emotion = params.get("emotion", "")
        max_duration = params.get("max_duration", 0)
        max_songs = params.get("max_songs", 0)
        
        print(f"正在生成播放列表...")
        print(f"  模式: {mode}")
        if query:
            print(f"  描述: {query}")
        if emotion:
            emotion_names = {"happy": "快乐", "sad": "悲伤", "energetic": "激情", 
                           "calm": "平静", "romantic": "浪漫", "nostalgic": "怀旧",
                           "angry": "愤怒", "focus": "专注", "party": "派对"}
            print(f"  情绪: {emotion_names.get(emotion, emotion)}")
        if max_duration:
            print(f"  时长: {max_duration}分钟")
        
        try:
            # 初始化情绪分析器（自动选择完整版或轻量版）
            try:
                from core.emotion_analyzer import AudioEmotionAnalyzer
            except ImportError:
                from core.emotion_analyzer_simple import SimpleEmotionAnalyzer as AudioEmotionAnalyzer
            
            emotion_analyzer = AudioEmotionAnalyzer(kimi_client=self.kimi)
            generator = PlaylistGenerator(self.librarian, emotion_analyzer=emotion_analyzer)
            
            criteria = {
                "mode": mode,
                "query": query,
                "emotion": emotion,
                "max_duration": max_duration,
                "description": query if mode == "smart" else (f"情绪: {emotion}" if emotion else "智能生成")
            }
            
            playlist = generator.generate(criteria)
            
            # 应用数量限制
            if max_songs > 0 and len(playlist.songs) > max_songs:
                playlist.songs = playlist.songs[:max_songs]
                playlist.total_duration = sum(s.get('duration', 240) for s in playlist.songs)
            
            # 保存到播放列表目录
            playlist_dir = Path(self.config.get("library", {}).get("path", ".")) / "Playlists"
            filepath = playlist.save(str(playlist_dir), use_relative_path=True)
            
            # 计算时长显示
            total_min = int(playlist.total_duration / 60)
            hours = total_min // 60
            mins = total_min % 60
            duration_str = f"{hours}小时{mins}分钟" if hours > 0 else f"{mins}分钟"
            
            # 情绪模式特殊提示
            emotion_hint = ""
            if mode == "emotion":
                emotion_desc = {
                    "happy": "充满正能量的快乐歌曲",
                    "sad": "温柔治愈适合静静聆听",
                    "energetic": "燃向高能激发活力",
                    "calm": "平静舒缓放松身心",
                    "romantic": "浪漫甜蜜适合二人世界",
                    "nostalgic": "经典怀旧唤起回忆",
                    "angry": "激烈发泄释放情绪",
                    "focus": "专注工作学习背景",
                    "party": "嗨翻全场派对必备"
                }
                
                # 检查是否使用了真实的情绪分析
                analyzed_count = len([s for s in playlist.songs if 'emotion_confidence' in s])
                if analyzed_count >= 3:
                    method_hint = f"（基于{analyzed_count}首歌曲的音频+歌词分析）"
                else:
                    method_hint = "（基于语义搜索，建议运行情绪分析工具）"
                
                emotion_hint = f"\n🎭 情绪标签: {emotion_desc.get(emotion, emotion)} {method_hint}"
            
            # 自动调用 foobar2000 播放
            foobar_result = self._play_with_foobar2000(str(filepath))
            
            if foobar_result:
                play_hint = f"\n🎧 {foobar_result}"
            else:
                play_hint = f"""\n💡 使用说明：
1. 打开 foobar2000
2. File → Load Playlist
3. 选择此文件即可导入"""
            
            return f"""✅ 播放列表已创建！

📋 {playlist.name}
🎵 {len(playlist.songs)} 首歌曲
⏱️ 总时长: {duration_str}
💾 保存位置: {filepath}{emotion_hint}{play_hint}

提示：播放列表使用相对路径，只要保持文件夹结构不变，移动播放列表文件也能正常播放。
"""
        except Exception as e:
            return f"创建播放列表时出错: {e}"


    def handle_smart_playlist(self, params: Dict) -> str:
        """Create a smart playlist from natural language description."""
        query = params.get("query", "")
        name = params.get("name", f"智能歌单_{query[:20]}")

        print(f"正在创建智能歌单: {name}")
        print(f"条件: {query}")

        from core.playlist_engine import PlaylistEngine
        engine = PlaylistEngine(self.librarian)
        result = engine.create_smart_playlist(query=query, name=name)

        if not result.get("songs"):
            return f"没有找到匹配「{query}」的歌曲。"

        songs = result["songs"]
        filepath = result.get("filepath", "")
        playlist_path = filepath or self._create_m3u8_playlist(songs, name)

        foobar_result = self._play_with_foobar2000(str(playlist_path)) if playlist_path else ""
        play_hint = f"\n🎧 {foobar_result}" if foobar_result else ""

        return f"🎵 智能歌单「{name}」已创建：{len(songs)} 首\n💾 {playlist_path}{play_hint}"

    def handle_list_playlists(self, params: Dict) -> str:
        """List all saved smart playlists."""
        from pathlib import Path
        playlist_dir = Path(__file__).parent.parent / "playlists"
        if not playlist_dir.exists():
            return "还没有保存的歌单。试试对我说「创建歌单 适合跑步听的歌」"

        files = sorted(playlist_dir.glob("*.m3u8"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return "还没有保存的歌单。"

        lines = [f"📋 已保存的歌单（共 {len(files)} 个）：", ""]
        for i, f in enumerate(files, 1):
            lines.append(f"  {i}. {f.stem}")

        lines.append("")
        lines.append("💡 输入「刷新歌单 N」更新动态歌单，或「删除歌单 N」移除歌单")
        return "\n".join(lines)

    def handle_refresh_playlist(self, params: Dict) -> str:
        """Refresh a dynamic playlist by index."""
        from pathlib import Path
        playlist_dir = Path(__file__).parent.parent / "playlists"
        files = sorted(playlist_dir.glob("*.m3u8"), key=lambda p: p.stat().st_mtime, reverse=True)

        index = params.get("index", 1) - 1
        if not files or index < 0 or index >= len(files):
            return "歌单编号无效。输入「查看歌单」查看所有歌单。"

        target = files[index]
        print(f"正在刷新歌单: {target.stem}")

        from core.playlist_engine import PlaylistEngine
        engine = PlaylistEngine(self.librarian)
        result = engine.refresh_playlist(str(target))

        return f"✅ 歌单「{target.stem}」已刷新，共 {result.get('count', 0)} 首歌。"

    def handle_delete_playlist(self, params: Dict) -> str:
        """Delete a saved playlist by index."""
        from pathlib import Path
        playlist_dir = Path(__file__).parent.parent / "playlists"
        files = sorted(playlist_dir.glob("*.m3u8"), key=lambda p: p.stat().st_mtime, reverse=True)

        index = params.get("index", 1) - 1
        if not files or index < 0 or index >= len(files):
            return "歌单编号无效。输入「查看歌单」查看所有歌单。"

        target = files[index]
        name = target.stem
        target.unlink()
        return f"🗑️ 歌单「{name}」已删除。"

