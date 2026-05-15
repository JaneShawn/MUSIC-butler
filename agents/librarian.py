"""
Librarian Agent - 本地音乐库管理 + RAG
"""
import os
import threading
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass

from .base_agent import BaseAgent
from core.vector_store import VectorStore
from core.audio_fingerprint import AudioFingerprint
from core.metadata_fetcher import MetadataFetcher
from core.kimi_client import KimiClient
from core.language_detector import detect_language
from core.music_library_db import get_library_db
from agents.metadata_enhancer import MetadataEnhancer, FileRenamer


@dataclass
class Song:
    """歌曲数据结构"""
    id: str
    file_path: str
    title: str
    artist: str
    album: str
    duration: float
    genre: str
    year: int
    fingerprint: Optional[str] = None
    embedding_id: Optional[str] = None
    tags: List[str] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
    
    def to_text(self) -> str:
        """转换为文本用于向量化"""
        return f"""
        Song: {self.title}
        Artist: {self.artist}
        Album: {self.album}
        Genre: {self.genre}
        Tags: {', '.join(self.tags)}
        """


class LibrarianAgent(BaseAgent):
    """
    图书管理员Agent
    - 扫描本地音乐文件
    - 音频指纹匹配识别
    - 元数据补全
    - RAG向量存储
    - 自然语言查询
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("Librarian", config)
        self.library_path = config.get("library", {}).get("path", "./music")
        self.supported_formats = config.get("library", {}).get(
            "supported_formats", [".flac", ".mp3", ".wav"]
        )
        
        # 初始化核心组件
        # 合并RAG配置到vector_store配置
        vector_config = config.get("vector_store", {})
        rag_config = config.get("rag", {})
        # 将RAG的embedding_model和device传递给vector_store
        if "embedding_model" not in vector_config and "embedding_model" in rag_config:
            vector_config["embedding_model"] = rag_config["embedding_model"]
        if "device" not in vector_config and "device" in rag_config:
            vector_config["device"] = rag_config["device"]
        
        self.vector_store = VectorStore(vector_config)
        self.fingerprinter = AudioFingerprint(config)
        self.metadata_fetcher = MetadataFetcher(config)
        
        # 相似度阈值配置
        self.similarity_threshold = rag_config.get("similarity_threshold", 0.5)
        
        # 内存中的歌曲索引
        self.songs: Dict[str, Song] = {}
        self._lock = threading.RLock()

        # 从持久化数据库恢复歌曲索引
        # music_library_db 是唯一可信数据源，ChromaDB 只是可重建的搜索索引
        self._load_songs_from_db()
        
        # 初始化Kimi客户端（用于查询意图理解和元数据解析）
        try:
            self.kimi = KimiClient(config=self.config)
            self.has_llm = True
            self.log("info", "Kimi API initialized for Librarian")
        except ValueError:
            self.kimi = None
            self.has_llm = False
            self.log("warning", "Kimi API not available, using keyword search")
        
        # 初始化元数据增强器（传入 Kimi 客户端用于智能解析）
        self.metadata_enhancer = MetadataEnhancer(cache={}, kimi_client=self.kimi)
        
    def run(self, operation: str = "scan", **kwargs) -> Any:
        """
        执行操作
        
        Args:
            operation: scan(扫描)|query(查询)|add(添加单首)|fix_metadata(修复元数据)
        """
        if operation == "scan":
            return self.scan_library()
        elif operation == "query":
            return self.query(kwargs.get("query_text", ""))
        elif operation == "add":
            return self.add_song(kwargs.get("file_path"))
        elif operation == "get_stats":
            return self.get_stats()
        elif operation == "fix_metadata":
            return self.fix_metadata(dry_run=kwargs.get("dry_run", True))
        else:
            raise ValueError(f"Unknown operation: {operation}")
    
    def fix_metadata(self, dry_run: bool = True, rename_files: bool = False, batch_size: int = 50, download_cover: bool = True) -> Dict:
        """
        修复缺失的元数据（支持在线搜索和重命名，支持专辑和封面）
        
        Args:
            dry_run: True=仅预览，False=实际执行
            rename_files: True=重命名文件为"歌手 - 歌名"格式
            batch_size: 每批处理数量（默认50，避免太久）
            download_cover: 是否下载并嵌入专辑封面
        """
        self.log("info", f"Starting metadata fix (dry_run={dry_run}, rename={rename_files}, download_cover={download_cover})")
        
        # 找出元数据不完整的歌曲
        with self._lock:
            incomplete_songs = [
                s for s in self.songs.values()
                if (s.artist == "Unknown" or s.title == "Unknown"
                    or not s.album or s.album == "Unknown"
                    or not LibrarianAgent.has_embedded_cover(s.file_path))
            ]
        total_incomplete = len(incomplete_songs)
        
        if not incomplete_songs:
            return {
                "total": len(self.songs),
                "incomplete": 0,
                "fixed": 0,
                "message": "所有歌曲元数据完整！"
            }
        
        # 分批处理
        to_process = incomplete_songs[:batch_size]
        remaining = total_incomplete - len(to_process)
        
        # 预估时间：每首至少 1 秒（速率限制）+ 网络延迟
        estimated_time = len(to_process) * 2  # QQ音乐搜索+封面下载需要更多时间
        
        print(f"🔍 发现 {total_incomplete} 首需要修复")
        if remaining > 0:
            print(f"⏱️  本次处理前 {len(to_process)} 首，剩余 {remaining} 首稍后处理")
        print(f"⏱️  预计耗时: {estimated_time:.0f} 秒 (按 Ctrl+C 可中断)")
        if download_cover:
            print(f"🖼️  将尝试获取专辑封面\n")
        else:
            print()
        
        fixed_count = 0
        failed_count = 0
        written_count = 0
        cover_count = 0
        renamed_count = 0
        skipped_write_count = 0  # 跳过写入计数（格式不支持等）
        write_failures = []  # 收集写入失败原因
        results = []
        
        renamer = FileRenamer(dry_run=dry_run)
        
        import time
        start_time = time.time()
        
        # 统计各数据源（添加 qq_music）
        source_stats = {"local_parse": 0, "llm_parse": 0, "netease": 0, "qq_music": 0, "musicbrainz": 0, "unknown": 0}
        
        try:
            for i, song in enumerate(to_process, 1):
                elapsed = time.time() - start_time
                progress = f"[{i}/{len(to_process)}]"
                eta = (elapsed / i) * (len(to_process) - i) if i > 0 else 0
                
                filename = Path(song.file_path).name
                print(f"\r{progress} 搜索: {filename[:40]:<40} (ETA: {eta:.0f}s)", end="", flush=True)
                
                try:
                    # 使用 QQ 音乐搜索（优先获取专辑和封面）
                    metadata = self.metadata_enhancer.search_by_filename(
                        filename, 
                        use_qq=True, 
                        download_cover=download_cover and not dry_run
                    )
                    
                    if metadata and metadata.get("title") and metadata.get("artist"):
                        new_artist = metadata["artist"]
                        new_title = metadata["title"]
                        new_name = self.metadata_enhancer.suggest_filename(metadata)
                        source = metadata.get("source", "unknown")
                        source_stats[source] = source_stats.get(source, 0) + 1
                        
                        # 获取封面路径
                        cover_path = metadata.get("cover_path") if download_cover else None
                        album_name = metadata.get("album", "")
                        
                        result_info = {
                            "file": filename,
                            "old_artist": song.artist,
                            "old_title": song.title,
                            "new_artist": new_artist,
                            "new_title": new_title,
                            "album": album_name,
                            "suggested_filename": new_name + Path(song.file_path).suffix,
                            "source": source,
                            "has_cover": bool(cover_path)
                        }
                        
                        if not dry_run:
                            song.artist = new_artist
                            song.title = new_title
                            if album_name:
                                song.album = album_name
                            if metadata.get("year"):
                                song.year = metadata["year"]
                            if metadata.get("genre"):
                                song.genre = metadata["genre"]
                            
                            # 写入元数据和封面
                            ext = Path(song.file_path).suffix.lower()
                            if ext in ['.flac', '.mp3', '.m4a', '.mp4']:
                                if self._write_metadata_to_file(song, cover_path):
                                    written_count += 1
                                    if cover_path:
                                        cover_count += 1
                                else:
                                    write_failures.append(f"{filename}: 写入失败")
                            else:
                                skipped_write_count += 1
                                write_failures.append(f"{filename}: 不支持格式 {ext}")
                            
                            if rename_files:
                                if renamer.rename(song.file_path, new_name):
                                    old_path = song.file_path
                                    song.file_path = str(Path(old_path).parent / (new_name + Path(old_path).suffix))
                                    renamed_count += 1
                        
                        results.append(result_info)
                        fixed_count += 1
                        source_icon = {"local_parse": "📄", "llm_parse": "🤖", "netease": "☁️", "qq_music": "🐧", "musicbrainz": "🎵"}.get(source, "✓")
                        cover_icon = " 🖼️" if cover_path else ""
                        album_info = f" [{album_name}]" if album_name else ""
                        print(f"\n{progress} {source_icon}{cover_icon} {new_artist} - {new_title}{album_info}")
                    else:
                        failed_count += 1
                        
                except Exception as e:
                    self.log("error", f"Failed to fix metadata for {song.file_path}: {e}")
                    failed_count += 1
                    
        except KeyboardInterrupt:
            print("\n\n⚠️ 用户中断，已保存当前进度")
        
        total_time = time.time() - start_time
        print(f"\n⏱️  实际耗时: {total_time:.1f} 秒")
        
        # 显示数据源统计
        source_names = {"local_parse": "本地解析", "llm_parse": "LLM解析", "netease": "网易云", "qq_music": "QQ音乐", "musicbrainz": "MusicBrainz"}
        source_summary = ", ".join([f"{source_names.get(k, k)}:{v}" for k, v in source_stats.items() if v > 0])
        if source_summary:
            print(f"📊 数据来源: {source_summary}")
        if cover_count > 0:
            print(f"🖼️  封面嵌入: {cover_count} 首")
        
        return {
            "total": len(self.songs),
            "incomplete": total_incomplete,
            "processed": len(to_process),
            "remaining": remaining,
            "fixed": fixed_count,
            "written": written_count if not dry_run else 0,
            "covers": cover_count if not dry_run else 0,
            "renamed": renamed_count if not dry_run else 0,
            "skipped_write": skipped_write_count if not dry_run else 0,
            "failed": failed_count,
            "source_stats": source_stats,
            "dry_run": dry_run,
            "rename_files": rename_files,
            "results": results,
            "write_failures": write_failures[:5] if write_failures else [],  # 最多返回5个失败原因
            "message": f"{'[预览] ' if dry_run else ''}找到 {fixed_count}/{len(to_process)} 首" + (f"，剩余 {remaining} 首待处理" if remaining > 0 else "")
        }
    
    def _parse_filename(self, file_path: str) -> dict:
        """
        智能解析文件名提取艺术家和标题
        
        支持多种格式：
        - "Artist - Title"
        - "Artist-Title"  
        - "Artist – Title" (中文破折号)
        - "Artist, Artist2 - Title"
        - "Title - Artist" (反向)
        - "Artist - Album - Title" (多段)
        """
        from pathlib import Path
        import re
        
        filename = Path(file_path).stem
        
        # 移除常见后缀 (Live, Explicit, feat.等)
        suffixes = [
            r'\s*\(.*?Live.*?\)',
            r'\s*\(.*?Explicit.*?\)',
            r'\s*\(.*?Remaster.*?\)',
            r'\s*\[.*?\]',
            r'\s*feat\..*$',
            r'\s*ft\..*$',
        ]
        clean_name = filename
        for pattern in suffixes:
            clean_name = re.sub(pattern, '', clean_name, flags=re.IGNORECASE)
        
        # 尝试多种分隔符
        separators = [' - ', ' – ', '—', ' -', '- ', '_', '｜']
        
        for sep in separators:
            if sep in clean_name:
                parts = clean_name.split(sep, 1)
                if len(parts) == 2:
                    artist = parts[0].strip()
                    title = parts[1].strip()
                    
                    # 如果艺术家是"Unknown"或看起来像标题，可能是反向的
                    if artist.lower() in ['unknown', 'various'] or len(artist) > len(title) * 2:
                        return {"artist": title, "title": artist}
                    
                    return {"artist": artist, "title": title}
        
        # 如果只有一个词，无法解析
        if ' ' not in clean_name:
            return None
        
        # 尝试最后一个空格分割（可能是"Title Artist"格式）
        words = clean_name.split()
        if len(words) >= 2:
            # 检查是否包含常见艺术家名
            common_artists = ['jay', 'kanye', 'taylor', 'adele', 'bruno', 'ed']
            lower_name = clean_name.lower()
            
            for artist_hint in common_artists:
                if artist_hint in lower_name:
                    # 找到艺术家名，以此为界分割
                    idx = lower_name.find(artist_hint)
                    if idx < len(clean_name) / 2:  # 艺术家通常在前面
                        return {
                            "artist": clean_name[:idx+len(artist_hint)].strip(),
                            "title": clean_name[idx+len(artist_hint):].strip()
                        }
        
        return None
    
    def _write_flac_metadata(self, song: Song, cover_path: str = None) -> bool:
        """写入FLAC元数据和封面"""
        from mutagen.flac import FLAC, Picture
        
        audio = FLAC(song.file_path)
        
        # 设置基本标签
        audio["TITLE"] = song.title
        audio["ARTIST"] = song.artist
        if song.album and song.album != "Unknown":
            audio["ALBUM"] = song.album
        if song.genre:
            audio["GENRE"] = song.genre
        if song.year:
            audio["DATE"] = str(song.year)
        
        # 写入封面
        if cover_path and os.path.exists(cover_path):
            try:
                # 清除现有图片
                audio.clear_pictures()
                
                # 添加新封面
                pic = Picture()
                with open(cover_path, "rb") as f:
                    pic.data = f.read()
                pic.type = 3  # 封面
                pic.mime = "image/jpeg"
                pic.desc = "Cover"
                audio.add_picture(pic)
            except Exception as e:
                self.log("warning", f"Failed to add cover to FLAC: {e}")
        
        # 保存
        audio.save()
        self.log("info", f"Written FLAC metadata: {song.artist} - {song.title}")
        return True
    
    def _write_mp3_metadata(self, song: Song, cover_path: str = None) -> bool:
        """写入MP3元数据和封面 (ID3标签)"""
        from mutagen.mp3 import MP3
        from mutagen.id3 import ID3, TIT2, TPE1, TALB, TCON, TDRC, APIC
        
        audio = MP3(song.file_path)
        
        # 确保有ID3标签
        if audio.tags is None:
            audio.add_tags()
        
        # 设置标签
        audio.tags["TIT2"] = TIT2(encoding=3, text=song.title)
        audio.tags["TPE1"] = TPE1(encoding=3, text=song.artist)
        
        if song.album and song.album != "Unknown":
            audio.tags["TALB"] = TALB(encoding=3, text=song.album)
        if song.genre:
            audio.tags["TCON"] = TCON(encoding=3, text=song.genre)
        if song.year:
            audio.tags["TDRC"] = TDRC(encoding=3, text=str(song.year))
        
        # 写入封面
        if cover_path and os.path.exists(cover_path):
            try:
                with open(cover_path, "rb") as f:
                    cover_data = f.read()
                
                # 移除现有封面
                for tag in list(audio.tags.keys()):
                    if tag.startswith("APIC"):
                        del audio.tags[tag]
                
                # 添加新封面
                audio.tags["APIC"] = APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=3,  # 封面
                    desc="Cover",
                    data=cover_data
                )
            except Exception as e:
                self.log("warning", f"Failed to add cover to MP3: {e}")
        
        # 保存
        audio.save()
        self.log("info", f"Written MP3 metadata: {song.artist} - {song.title}")
        return True
    
    def _write_m4a_metadata(self, song: Song, cover_path: str = None) -> bool:
        """写入M4A元数据和封面"""
        from mutagen.mp4 import MP4, MP4Cover
        
        audio = MP4(song.file_path)
        
        # M4A使用不同的标签名
        audio["\xa9nam"] = song.title  # 标题
        audio["\xa9ART"] = song.artist  # 艺术家
        
        if song.album and song.album != "Unknown":
            audio["\xa9alb"] = song.album
        if song.genre:
            audio["\xa9gen"] = song.genre
        if song.year:
            audio["\xa9day"] = str(song.year)
        
        # 写入封面
        if cover_path and os.path.exists(cover_path):
            try:
                with open(cover_path, "rb") as f:
                    cover_data = f.read()
                
                # M4A 封面格式
                audio["covr"] = [MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_JPEG)]
            except Exception as e:
                self.log("warning", f"Failed to add cover to M4A: {e}")
        
        # 保存
        audio.save()
        self.log("info", f"Written M4A metadata: {song.artist} - {song.title}")
        return True
    
    def _write_metadata_to_file(self, song: Song, cover_path: str = None) -> bool:
        """
        将元数据写入文件标签（支持封面）
        
        支持格式: FLAC, MP3, M4A
        """
        try:
            from pathlib import Path
            ext = Path(song.file_path).suffix.lower()
            
            if ext == ".flac":
                return self._write_flac_metadata(song, cover_path)
            elif ext == ".mp3":
                return self._write_mp3_metadata(song, cover_path)
            elif ext in [".m4a", ".mp4"]:
                return self._write_m4a_metadata(song, cover_path)
            else:
                self.log("warning", f"Unsupported format for metadata writing: {ext}")
                return False
                
        except Exception as e:
            self.log("error", f"Failed to write metadata to {song.file_path}: {e}")
            return False
    
    @staticmethod
    def has_embedded_cover(file_path: str) -> bool:
        """检测音频文件是否已有内嵌封面（FLAC/MP3/M4A）。"""
        ext = Path(file_path).suffix.lower()
        try:
            if ext == ".flac":
                from mutagen.flac import FLAC
                return len(FLAC(file_path).pictures) > 0
            elif ext == ".mp3":
                from mutagen.id3 import ID3
                tags = ID3(file_path)
                return any(k.startswith("APIC") for k in (tags.keys() if tags else []))
            elif ext in (".m4a", ".mp4"):
                from mutagen.mp4 import MP4
                return "covr" in MP4(file_path)
        except Exception:
            pass
        return False

    def scan_library(self) -> Dict:
        """扫描整个音乐库（自动清理已删除文件的残留索引）"""
        self.log("info", f"Scanning library at: {self.library_path}")

        music_files = self._find_music_files()
        current_ids = {self._file_to_id(fp) for fp in music_files}
        self.log("info", f"Found {len(music_files)} music files")

        with self._lock:
            # 1. 清理已删除的"幽灵歌曲"（同时清理内存、ChromaDB、SQLite）
            lib_db = get_library_db()
            removed = 0
            ghost_ids = [sid for sid, song in list(self.songs.items()) if sid not in current_ids]
            for song_id in ghost_ids:
                try:
                    self.vector_store.delete(song_id)
                    lib_db.delete(song_id)
                    del self.songs[song_id]
                    removed += 1
                except Exception as e:
                    self.log("warning", f"Failed to remove ghost song {song_id}: {e}")

            if removed:
                print(f"[Librarian] 清理了 {removed} 首已删除文件的残留索引（已同步清理 SQLite）")

            # 2. 处理所有文件：新文件完整索引，已有文件同步到 DB
            new_songs = []
            synced = 0
            for file_path in music_files:
                song_id = self._file_to_id(file_path)

                if song_id in self.songs:
                    # 已有文件：轻量级同步到 music_library_db（确保DB有记录）
                    song = self.songs[song_id]
                    if not lib_db.get_record(song.artist, song.title):
                        lib_db.update_or_create(
                            file_path=song.file_path,
                            title=song.title,
                            artist=song.artist,
                            album=song.album,
                            genre=song.genre,
                            year=str(song.year),
                            duration=str(song.duration)
                        )
                        synced += 1
                    continue

                # 新文件：完整解析并索引
                song = self._process_file(file_path)
                if song:
                    self.songs[song_id] = song
                    new_songs.append(song)

            # 添加到向量数据库和 music_library_db
            if new_songs:
                self._index_songs(new_songs)

            if synced:
                print(f"[Librarian] 同步了 {synced} 首已有歌曲到 music_library_db")

            result = {
                "total_files": len(music_files),
                "new_songs": len(new_songs),
                "synced": synced,
                "removed": removed,
                "total_indexed": len(self.songs)
            }

        self.log("info", f"Scan complete: {result}")
        return result
    
    def query(self, query_text: str, top_k: int = 10, use_threshold: bool = True) -> List[Dict]:
        """
        RAG查询 - 自然语言搜索歌曲（集成LLM意图理解）
        
        示例：
        - "推荐一些周杰伦的歌" → 搜索artist:周杰伦
        - "适合下雨听的国语歌" → 搜索mood:安静 language:国语
        - "90年代的粤语摇滚" → 搜索year:1990s genre:rock language:粤语
        
        Args:
            query_text: 自然语言查询文本
            top_k: 返回结果数
            use_threshold: 是否使用相似度阈值过滤低质量结果
        """
        self.log("info", f"Query: {query_text}")
        
        # 使用LLM理解查询意图
        intent = None
        if self.has_llm:
            try:
                intent = self.kimi.analyze_query_intent(query_text)
                self.log("info", f"Query intent: {intent}")
                
                # 根据意图构造优化查询
                enhanced_query = self._build_enhanced_query(intent, query_text)
            except Exception as e:
                self.log("error", f"Intent analysis failed: {e}")
                enhanced_query = query_text
        else:
            enhanced_query = query_text
        
        # 执行向量搜索（带阈值过滤）
        print(f"  [搜索] 查询: '{enhanced_query}'")
        
        # 特殊处理：如果只有语言条件，使用metadata过滤（更精准）
        # 检查是否只有语言，没有其他条件
        has_language = intent and intent.get("language")
        has_other = intent and any([
            intent.get("artist"), intent.get("genre"), intent.get("mood"), intent.get("year_range")
        ])
        if has_language and not has_other:
            print(f"  [搜索] 使用语言metadata过滤: {intent['language']}")
            return self._filter_by_language(intent["language"], top_k)
        
        # 特殊处理：如果有 artist 条件，使用精确匹配（向量搜索对 artist:xxx 语法不可靠）
        if intent and intent.get("artist"):
            return self._filter_by_artist(intent, top_k)
        
        # 特殊处理：如果有 mood 条件但没有 artist，使用情绪缓存过滤（向量搜索对情绪语义不可靠）
        if intent and intent.get("mood") and not intent.get("artist"):
            return self._filter_by_mood(intent["mood"], top_k)
        
        # 执行向量搜索
        if use_threshold:
            results = self.vector_store.search_with_threshold(
                enhanced_query, 
                top_k=top_k,
                threshold=self.similarity_threshold
            )
        else:
            results = self.vector_store.search(enhanced_query, top_k=top_k)
        
        print(f"  [搜索] 向量搜索找到 {len(results)} 个结果")
        
        # 组装返回结果
        songs = []
        for result in results:
            song_id = result.get("id")
            if song_id and song_id in self.songs:
                song = self.songs[song_id]
                songs.append({
                    "song": song,
                    "similarity": result.get("score"),
                    "metadata": result.get("metadata", {}),
                    "intent": intent
                })
        
        return songs
    
    def _filter_by_language(self, language: str, top_k: int) -> List[Dict]:
        """根据语言metadata过滤歌曲（精确匹配）
        
        不再每首歌都重新检测语言（400+首歌走6层检测太慢），
        而是从 music_library_db 读取持久化的语言信息，DB缺失时才补检测。
        """
        lib_db = get_library_db()
        results = []
        missing = 0
        
        with self._lock:
            _songs_snapshot = list(self.songs.items())
        for song_id, song in _songs_snapshot:
            # 优先从持久化 DB 读取语言（O(1)，不触发网络请求）
            record = lib_db.get_record(song.artist, song.title)
            if record and record.language:
                detected_lang = record.language
            else:
                # DB 缺失，补检测并写入 DB（只发生在首次查询或数据迁移后）
                detected_lang, lang_source, _ = self._detect_language(song)
                lib_db.update_language(song.artist, song.title, detected_lang, lang_source)
                missing += 1
            
            if detected_lang == language:
                results.append({
                    "song": song,
                    "similarity": 1.0,
                    "metadata": {"language": language},
                    "intent": {"language": language}
                })
        
        print(f"  [搜索] 语言过滤找到 {len(results)} 首{language}歌" + 
              (f" (补录 {missing} 首语言到DB)" if missing else ""))
        
        # 如果结果太多，随机采样保持多样性
        if len(results) > top_k:
            import random
            results = random.sample(results, top_k)
            print(f"  [搜索] 随机选取 {top_k} 首展示")
        
        return results
    
    def _map_mood_to_emotion(self, mood: str) -> Optional[str]:
        """将中文/英文情绪词映射到情绪标签（含场景→情绪）"""
        mood_lower = mood.lower().strip()
        mapping = {
            # === 核心情绪 ===
            'happy': 'happy', '开心': 'happy', '快乐': 'happy', '欢乐': 'happy', '高兴': 'happy', '愉快': 'happy',
            'sad': 'sad', '悲伤': 'sad', '难过': 'sad', '伤心': 'sad', 'melancholy': 'sad', '哭': 'sad',
            'energetic': 'energetic', '激情': 'energetic', '燃': 'energetic', '热血': 'energetic', '强烈': 'energetic',
            'calm': 'calm', '平静': 'calm', '安静': 'calm', '放松': 'calm', '舒缓': 'calm', '轻音乐': 'calm', 'sleepy': 'calm',
            'romantic': 'romantic', '浪漫': 'romantic', '甜蜜': 'romantic', '温柔': 'romantic', '爱情': 'romantic', '情歌': 'romantic', '心动': 'romantic',
            'nostalgic': 'nostalgic', '怀旧': 'nostalgic', '经典': 'nostalgic', '回忆': 'nostalgic', '老歌': 'nostalgic', '往日': 'nostalgic',
            'angry': 'angry', '愤怒': 'angry', '怒': 'angry', '恨': 'angry', 'rage': 'angry',
            'focus': 'focus', '专注': 'focus', '工作': 'focus', '学习': 'focus', 'background': 'focus',
            'party': 'party', '派对': 'party', '嗨': 'party', '舞': 'party', 'club': 'party', 'dance': 'party',
            # === 天气场景 → 情绪 ===
            '下雨': 'sad', '雨天': 'sad', 'rain': 'sad', 'raining': 'sad', '雨': 'sad',
            '晴天': 'happy', 'sunny': 'happy', '阳光': 'happy',
            '阴天': 'nostalgic', 'cloudy': 'nostalgic',
            '雪': 'romantic', 'snow': 'romantic', '下雪': 'romantic',
            # === 时间段场景 → 情绪 ===
            '晚上': 'calm', 'night': 'calm', '夜晚': 'calm',
            '深夜': 'sad', 'latenight': 'sad', '半夜': 'sad',
            '早晨': 'happy', '早上': 'happy', 'morning': 'happy',
            # === 活动场景 → 情绪 ===
            '运动': 'energetic', 'workout': 'energetic', '健身': 'energetic',
            '跑步': 'energetic', 'running': 'energetic', '慢跑': 'energetic',
            '学习': 'focus', 'study': 'focus', '自习': 'focus',
            '工作': 'focus', '办公': 'focus',
            '睡觉': 'calm', '睡眠': 'calm', 'sleep': 'calm', '助眠': 'calm',
            '睡前': 'calm', 'bedtime': 'calm',
            '通勤': 'focus', 'commute': 'focus', '路上': 'focus',
            '开车': 'energetic', 'driving': 'energetic', '驾车': 'energetic',
            '洗澡': 'happy', 'shower': 'happy',
            '咖啡': 'focus', 'coffee': 'focus', 'cafe': 'focus',
        }
        return mapping.get(mood_lower)
    
    def _filter_by_mood(self, mood: str, top_k: int) -> List[Dict]:
        """根据情绪标签过滤歌曲（优先用 emotion_cache，fallback SQLite，最后向量搜索）
        
        向量搜索对情绪语义匹配不可靠，"开心"可能返回《画心》。
        优先使用已分析的真实情绪标签（含手动纠正）， fallback 到语义搜索。
        """
        target_emotion = self._map_mood_to_emotion(mood)
        if not target_emotion:
            return []
        
        from core.emotion_analyzer_simple import SimpleEmotionAnalyzer
        analyzer = SimpleEmotionAnalyzer()
        lib_db = get_library_db()
        
        results = []
        
        with self._lock:
            _songs_snapshot = list(self.songs.items())
        for song_id, song in _songs_snapshot:
            matched = False
            sim = 0.5

            # L1: emotion_cache（含手动纠正，source='manual' 优先级最高）
            cache_key = analyzer._get_file_hash(song.file_path)
            if cache_key in analyzer._cache:
                cached = analyzer._cache[cache_key]
                if cached.get('emotion') == target_emotion:
                    matched = True
                    sim = cached.get('confidence', 0.5)
            
            # L2: SQLite（用户通过 update_song_info 或 correct_emotion 写入）
            if not matched:
                record = lib_db.get_record(song.artist, song.title)
                if record and record.emotion == target_emotion:
                    matched = True
                    sim = 0.8
            
            if matched:
                results.append({
                    "song": song,
                    "similarity": sim,
                    "metadata": {"emotion": target_emotion},
                    "intent": {"mood": mood}
                })
        
        # 缓存+DB 命中不足时，fallback 向量搜索补充
        if len(results) < top_k:
            needed = top_k - len(results)
            fallback = self.vector_store.search(mood, top_k=needed + 10)
            seen_paths = {r["song"].file_path for r in results}
            for r in fallback:
                song = self.songs.get(r.get("id"))
                if song and song.file_path not in seen_paths:
                    results.append({
                        "song": song,
                        "similarity": r.get("score", 0.5),
                        "metadata": {"emotion": target_emotion},
                        "intent": {"mood": mood}
                    })
                    if len(results) >= top_k:
                        break
        
        if len(results) > top_k:
            import random
            results = random.sample(results, top_k)
        
        print(f"  [搜索] Mood过滤: {mood}({target_emotion}) 找到{len(results)}首")
        return results
    
    def _filter_by_artist(self, intent: Dict, top_k: int) -> List[Dict]:
        """根据 artist 匹配，并叠加其他 metadata 条件（language/genre/year等）
        
        向量搜索对 'artist:xxx' 语法不可靠，embedding 模型不理解标签语义，
        容易返回不相关结果。对于 artist 查询，用子串模糊匹配更实用
        （如输入"Kanye"能匹配"Kanye West"）。
        """
        target_artist = intent["artist"]
        target_lower = target_artist.lower()
        results = []
        lib_db = get_library_db()
        
        with self._lock:
            _songs_snapshot = list(self.songs.items())
        for song_id, song in _songs_snapshot:
            # 子串模糊匹配：输入 "Kanye" 匹配 "Kanye West"
            if target_lower not in song.artist.lower():
                continue
            
            # 叠加 language 条件
            if intent.get("language"):
                record = lib_db.get_record(song.artist, song.title)
                song_lang = record.language if record and record.language else None
                if not song_lang:
                    song_lang, lang_source, _ = self._detect_language(song)
                    lib_db.update_language(song.artist, song.title, song_lang, lang_source)
                if song_lang != intent["language"]:
                    continue
            
            # 叠加 genre 条件
            if intent.get("genre"):
                song_genre = (song.genre or "").lower()
                if intent["genre"].lower() not in song_genre:
                    continue
            
            # 叠加 year_range 条件
            if intent.get("year_range"):
                if not self._match_year_range(song.year, intent["year_range"]):
                    continue
            
            results.append({
                "song": song,
                "similarity": 1.0,
                "metadata": {"artist": target_artist},
                "intent": intent
            })
        
        # 如果结果太多，随机采样保持多样性
        if len(results) > top_k:
            import random
            results = random.sample(results, top_k)
        
        print(f"  [搜索] Artist匹配: {target_artist} ({len(results)}首)")
        return results
    
    def _match_year_range(self, song_year: Optional[int], year_range: str) -> bool:
        """匹配年代范围，如 '1990s', '2000s', '2010' 等"""
        if not song_year:
            return False
        
        yr = year_range.strip().lower()
        
        # 精确年份匹配，如 "1995"
        if yr.isdigit():
            return song_year == int(yr)
        
        # 年代匹配，如 "1990s" → 1990-1999
        if yr.endswith("s") and yr[:-1].isdigit():
            decade_start = int(yr[:-1])
            return decade_start <= song_year < decade_start + 10
        
        # 范围匹配，如 "1990-2000"
        if "-" in yr:
            parts = yr.split("-")
            if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
                start, end = int(parts[0].strip()), int(parts[1].strip())
                return start <= song_year <= end
        
        return False
    
    def _build_enhanced_query(self, intent: Dict, original: str) -> str:
        """
        根据意图构造优化的向量搜索查询
        """
        parts = []
        
        # 艺术家权重最高
        if intent.get("artist"):
            parts.append(f"artist:{intent['artist']}")
        
        # 流派
        if intent.get("genre"):
            parts.append(intent["genre"])
        
        # 语言
        if intent.get("language"):
            parts.append(intent["language"])
        
        # 情绪/场景
        if intent.get("mood"):
            parts.append(intent["mood"])
        
        # 年代（作为标签）
        if intent.get("year_range"):
            parts.append(intent["year_range"])
        
        # 如果解析出的内容太少，保留原查询
        # 但至少要有一个有效条件（如语言、流派等）
        if len(parts) == 0:
            return original
        
        # 即使只有一个条件（如语言），也使用它进行搜索
        return " ".join(parts)
    
    def add_song(self, file_path: str) -> Optional[Song]:
        """添加单首歌曲"""
        song_id = self._file_to_id(file_path)

        with self._lock:
            if song_id in self.songs:
                self.log("warning", f"Song already exists: {file_path}")
                return self.songs[song_id]

            song = self._process_file(file_path)
            if song:
                self.songs[song_id] = song
                self._index_songs([song])
                self.log("info", f"Added song: {song.title} - {song.artist}")
                return song
        return None
    
    def get_stats(self) -> Dict:
        """获取库统计信息"""
        from collections import Counter
        
        # 统计艺术家
        artist_counter = Counter()
        genre_counter = Counter()
        
        with self._lock:
            _songs_snapshot = list(self.songs.values())

        for song in _songs_snapshot:
            if song.artist:
                artist_counter[song.artist] += 1
            if song.genre:
                # 处理多流派（用逗号或斜杠分隔）
                genres = [g.strip() for g in song.genre.replace('/', ',').split(',')]
                for g in genres:
                    if g:
                        genre_counter[g] += 1

        return {
            "total_songs": len(self.songs),
            "artists": len(artist_counter),
            "albums": len(set(s.album for s in _songs_snapshot)),
            "genres": len(genre_counter),
            "top_artists": artist_counter.most_common(10),  # Top 10 艺术家
            "top_genres": genre_counter.most_common(10),    # Top 10 流派
        }
    
    def _find_music_files(self) -> List[str]:
        """查找所有音乐文件"""
        files = []
        for ext in self.supported_formats:
            files.extend(Path(self.library_path).rglob(f"*{ext}"))
        return [str(f) for f in files]
    
    def _file_to_id(self, file_path: str) -> str:
        """生成歌曲唯一ID"""
        import hashlib
        return hashlib.md5(file_path.encode()).hexdigest()[:16]
    
    def _load_songs_from_db(self):
        """从 music_library_db 恢复歌曲索引（唯一可信数据源）"""
        try:
            lib_db = get_library_db()
            records = lib_db.list_all()
            
            if records:
                for rec in records:
                    song_id = self._file_to_id(rec.file_path)
                    song = Song(
                        id=song_id,
                        file_path=rec.file_path,
                        title=rec.title or Path(rec.file_path).stem,
                        artist=rec.artist or "Unknown",
                        album=rec.album or "Unknown",
                        duration=float(rec.duration) if rec.duration else 0.0,
                        genre=rec.genre or "",
                        year=int(rec.year) if rec.year else 0,
                        fingerprint=None,
                        embedding_id=song_id,
                        tags=[]
                    )
                    self.songs[song_id] = song
                
                self.log("info", f"Restored {len(records)} songs from music_library_db")
                print(f"[Librarian] 已从 music_library_db 恢复 {len(records)} 首歌曲")
                return
            
            # DB 为空但 ChromaDB 有数据：迁移旧数据并回填到 DB
            self._migrate_from_chroma_to_db()
            
        except Exception as e:
            self.log("warning", f"Failed to restore from music_library_db: {e}")
    
    def _migrate_from_chroma_to_db(self):
        """ChromaDB 数据迁移到 music_library_db（SQLite 版，一次性回填）"""
        try:
            lib_db = get_library_db()
            migrated = lib_db.migrate_from_chroma(self.vector_store)
            
            if migrated > 0:
                # 迁移完成后重新从 DB 加载到内存
                self.songs.clear()
                self._load_songs_from_db()
        except Exception as e:
            self.log("warning", f"Failed to migrate from ChromaDB: {e}")
    
    def _process_file(self, file_path: str) -> Optional[Song]:
        """处理单个文件"""
        try:
            # 1. 解析本地元数据
            metadata = self.metadata_fetcher.extract_from_file(file_path)
            
            # 2. 音频指纹识别
            fingerprint = self.fingerprinter.fingerprint(file_path)
            
            # 3. 如果指纹匹配到，补全元数据
            if fingerprint:
                external_meta = self.metadata_fetcher.query_by_fingerprint(fingerprint)
                if external_meta:
                    metadata.update(external_meta)
            
            song_id = self._file_to_id(file_path)
            song = Song(
                id=song_id,
                file_path=file_path,
                title=metadata.get("title", Path(file_path).stem),
                artist=metadata.get("artist", "Unknown"),
                album=metadata.get("album", "Unknown"),
                duration=metadata.get("duration", 0),
                genre=metadata.get("genre", ""),
                year=metadata.get("year", 0),
                fingerprint=fingerprint,
                tags=metadata.get("tags", [])
            )
            
            return song
            
        except Exception as e:
            self.log("error", f"Failed to process {file_path}: {e}")
            return None
    
    def _detect_language(self, song: Song) -> Tuple[str, str, float]:
        """
        使用新的LanguageDetector检测
        返回: (语言, 来源, 置信度)
        来源包含 'manual' 时表示用户手动纠正，扫描时不得覆盖
        """
        language, source, confidence = detect_language(
            song.title, song.artist, song.file_path
        )
        
        # 调试输出
        if source in ['artist_keyword', 'netease_api', 'manual']:
            print(f"    [语言检测] {song.artist} - {song.title} = {language} ({source})")
        
        return language, source, confidence
    
    def _index_songs(self, songs: List[Song]):
        """将歌曲添加到向量数据库和音乐库数据库"""
        texts = []
        ids = []
        metadatas = []
        lang_stats = {}
        
        # 获取音乐库数据库
        lib_db = get_library_db()
        
        for s in songs:
            # 检测语言
            language, lang_source, lang_conf = self._detect_language(s)
            lang_stats[language] = lang_stats.get(language, 0) + 1
            
            # 更新到音乐库数据库
            # 如果来源是 manual（用户手动纠正），保留 manual 标记
            lib_db.update_or_create(
                file_path=s.file_path,
                title=s.title,
                artist=s.artist,
                album=s.album,
                genre=s.genre,
                year=str(s.year) if s.year else "",
                duration=str(s.duration) if s.duration else "",
                language=language,
                language_source=lang_source
            )
            
            # 调试输出：显示各类语言的采样
            artist_title = f"{s.artist or ''} {s.title or ''}"
            has_chinese = any('\u4e00' <= c <= '\u9fff' for c in artist_title)
            has_japanese = any(c in artist_title for c in 'のはがでとにをんアイウエオカキクケコ')
            has_korean = any('\uac00' <= c <= '\ud7a3' for c in artist_title)
            
            # 采样显示：前2首 + 前2首日文 + 前2首韩文 + 前2首中文误判
            if len(texts) < 2:
                print(f"  [索引] {s.artist} - {s.title} -> 语言: {language}")
            elif has_korean and lang_stats.get('韩语', 0) <= 2:
                print(f"  [索引] {s.artist} - {s.title} -> 语言: {language}")
            elif has_japanese and language == '日语' and lang_stats.get('日语', 0) <= 2:
                print(f"  [索引] {s.artist} - {s.title} -> 语言: {language}")
            elif has_chinese and language not in ['国语', '粤语'] and lang_stats.get('误判', 0) <= 2:
                print(f"  [误判?] {s.artist} - {s.title} -> 被识别为: {language}")
            
            # 构建索引文本（包含语言信息以便语义搜索）
            text_parts = [s.title or "", s.artist or "", s.album or ""]
            if language:
                text_parts.append(language)
            if s.genre:
                text_parts.append(s.genre)
            
            texts.append(" ".join(filter(None, text_parts)))
            ids.append(s.id)
            metadatas.append({
                "title": s.title,
                "artist": s.artist,
                "album": s.album,
                "genre": s.genre,
                "language": language,
                "file_path": s.file_path
            })
        
        self.vector_store.add(texts, ids, metadatas)
        
        # 打印语言分布统计
        print(f"  [语言分布] {dict(sorted(lang_stats.items(), key=lambda x: -x[1]))}")
        
        self.log("info", f"Indexed {len(songs)} songs to vector store")


_librarian_instance = None


def get_librarian(config: dict = None) -> "LibrarianAgent":
    global _librarian_instance
    if _librarian_instance is None:
        if config is None:
            import yaml
            from pathlib import Path
            config_path = Path(__file__).resolve().parent.parent / "config.yaml"
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
        _librarian_instance = LibrarianAgent(config)
    return _librarian_instance
