# -*- coding: utf-8 -*-
"""
音乐库数据库 - SQLite 版
管理所有歌曲的完整信息，支持导出为CSV，可用Excel编辑
"""

import csv
import hashlib
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass


@dataclass
class SongRecord:
    """歌曲完整记录"""
    # 基本信息
    file_path: str
    title: str
    artist: str
    album: str = ""
    genre: str = ""
    year: str = ""
    duration: str = ""
    
    # 语言信息（可编辑）
    language: str = ""
    language_source: str = ""
    
    # 情绪信息（可编辑）
    emotion: str = ""
    emotion_confidence: str = ""
    
    # 歌词信息
    has_lyrics: str = "否"
    lyrics_source: str = ""
    
    # 播放统计
    play_count: str = "0"
    last_played: str = ""
    
    # 用户备注
    notes: str = ""
    
    # 系统字段
    updated_at: str = ""
    created_at: str = ""


# 表字段（与 SongRecord 一一对应）
SONG_COLUMNS = [
    'id', 'file_path', 'title', 'artist', 'album', 'genre', 'year', 'duration',
    'language', 'language_source', 'emotion', 'emotion_confidence',
    'has_lyrics', 'lyrics_source', 'play_count', 'last_played', 'notes',
    'updated_at', 'created_at'
]


class MusicLibraryDB:
    """音乐库数据库管理器（SQLite 版）"""
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_file = self.data_dir / "music_library.db"
        self.csv_file = self.data_dir / "music_library.csv"
        
        # 初始化数据库连接和表结构
        self._init_db()
        
        # 兼容旧版：如果 JSON 文件存在，自动迁移到 SQLite
        self._migrate_from_json()
    
    def _init_db(self):
        """初始化数据库表结构"""
        with sqlite3.connect(self.db_file) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS songs (
                    id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    album TEXT DEFAULT '',
                    genre TEXT DEFAULT '',
                    year TEXT DEFAULT '',
                    duration TEXT DEFAULT '',
                    language TEXT DEFAULT '',
                    language_source TEXT DEFAULT '',
                    emotion TEXT DEFAULT '',
                    emotion_confidence TEXT DEFAULT '',
                    has_lyrics TEXT DEFAULT '否',
                    lyrics_source TEXT DEFAULT '',
                    play_count TEXT DEFAULT '0',
                    last_played TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    updated_at TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # 创建索引，加速常用查询
            conn.execute("CREATE INDEX IF NOT EXISTS idx_artist ON songs(artist)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_language ON songs(language)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_emotion ON songs(emotion)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_genre ON songs(genre)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_year ON songs(year)")
            conn.commit()
    
    def _migrate_from_json(self):
        """从旧版 JSON 文件迁移数据（一次性）"""
        json_file = self.data_dir / "music_library.json"
        if not json_file.exists():
            return
        
        try:
            import json
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not data:
                return
            
            migrated = 0
            for key, item in data.items():
                self._insert_or_replace_record(SongRecord(**item))
                migrated += 1
            
            print(f"[MusicLibraryDB] 已从 JSON 迁移 {migrated} 条记录到 SQLite")
            
            # 迁移完成后重命名旧文件，避免重复迁移
            json_file.rename(json_file.with_suffix('.json.bak'))
            
        except Exception as e:
            print(f"[WARN] JSON 迁移失败: {e}")
    
    @staticmethod
    def _file_to_id(file_path: str) -> str:
        """根据文件路径生成唯一 ID"""
        return hashlib.md5(file_path.encode('utf-8')).hexdigest()[:16]
    
    def _row_to_record(self, row: sqlite3.Row) -> SongRecord:
        """将数据库行转换为 SongRecord"""
        return SongRecord(
            file_path=row['file_path'],
            title=row['title'],
            artist=row['artist'],
            album=row['album'] or '',
            genre=row['genre'] or '',
            year=str(row['year']) if row['year'] else '',
            duration=str(row['duration']) if row['duration'] else '',
            language=row['language'] or '',
            language_source=row['language_source'] or '',
            emotion=row['emotion'] or '',
            emotion_confidence=row['emotion_confidence'] or '',
            has_lyrics=row['has_lyrics'] or '否',
            lyrics_source=row['lyrics_source'] or '',
            play_count=str(row['play_count']) if row['play_count'] else '0',
            last_played=row['last_played'] or '',
            notes=row['notes'] or '',
            updated_at=row['updated_at'] or '',
            created_at=row['created_at'] or ''
        )
    
    def _insert_or_replace_record(self, record: SongRecord):
        """插入或替换单条记录（内部使用）"""
        song_id = self._file_to_id(record.file_path)
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("""
                INSERT OR REPLACE INTO songs (
                    id, file_path, title, artist, album, genre, year, duration,
                    language, language_source, emotion, emotion_confidence,
                    has_lyrics, lyrics_source, play_count, last_played, notes,
                    updated_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                song_id, record.file_path, record.title, record.artist,
                record.album, record.genre, record.year, record.duration,
                record.language, record.language_source, record.emotion,
                record.emotion_confidence, record.has_lyrics, record.lyrics_source,
                record.play_count, record.last_played, record.notes,
                record.updated_at, record.created_at
            ))
            conn.commit()
    
    def update_or_create(self, file_path: str, title: str, artist: str,
                        album: str = "", genre: str = "", year: str = "",
                        duration: str = "", **kwargs) -> SongRecord:
        """更新或创建歌曲记录"""
        song_id = self._file_to_id(file_path)
        now = datetime.now().isoformat()
        
        # 先查询是否已存在
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM songs WHERE id = ?", (song_id,)
            )
            existing = cursor.fetchone()
        
        if existing:
            # 更新：只更新非空字段
            updates = {
                'file_path': file_path,
                'title': title,
                'artist': artist,
                'updated_at': now
            }
            if album: updates['album'] = album
            if genre: updates['genre'] = genre
            if year: updates['year'] = year
            if duration: updates['duration'] = duration
            
            # 处理 kwargs 中的额外字段
            for k, v in kwargs.items():
                if v and k in SONG_COLUMNS:
                    updates[k] = v
            
            # 构建 UPDATE SQL
            set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
            values = list(updates.values()) + [song_id]
            
            with sqlite3.connect(self.db_file) as conn:
                conn.execute(f"UPDATE songs SET {set_clause} WHERE id = ?", values)
                conn.commit()
        else:
            # 创建新记录
            record = SongRecord(
                file_path=file_path,
                title=title,
                artist=artist,
                album=album,
                genre=genre,
                year=year,
                duration=duration,
                created_at=now,
                updated_at=now,
                **kwargs
            )
            self._insert_or_replace_record(record)
        
        # 返回更新后的记录
        return self.get_record(artist, title) or SongRecord(
            file_path=file_path, title=title, artist=artist
        )
    
    def update_language(self, artist: str, title: str, language: str, source: str = "manual"):
        """更新语言信息"""
        with sqlite3.connect(self.db_file) as conn:
            conn.execute(
                """UPDATE songs SET language = ?, language_source = ?, updated_at = ?
                   WHERE artist = ? AND title = ?""",
                (language, source, datetime.now().isoformat(), artist, title)
            )
            conn.commit()
    
    def update_emotion(self, artist: str, title: str, emotion: str, confidence: str):
        """更新情绪信息"""
        with sqlite3.connect(self.db_file) as conn:
            conn.execute(
                """UPDATE songs SET emotion = ?, emotion_confidence = ?, updated_at = ?
                   WHERE artist = ? AND title = ?""",
                (emotion, confidence, datetime.now().isoformat(), artist, title)
            )
            conn.commit()
    
    def update_lyrics_status(self, artist: str, title: str, has_lyrics: bool, source: str = ""):
        """更新歌词状态"""
        flag = "是" if has_lyrics else "否"
        with sqlite3.connect(self.db_file) as conn:
            conn.execute(
                """UPDATE songs SET has_lyrics = ?, lyrics_source = ?, updated_at = ?
                   WHERE artist = ? AND title = ?""",
                (flag, source, datetime.now().isoformat(), artist, title)
            )
            conn.commit()
    
    def get_record(self, artist: str, title: str) -> Optional[SongRecord]:
        """获取单条记录（artist + title 匹配，返回第一条）"""
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM songs WHERE artist = ? AND title = ? LIMIT 1",
                (artist, title)
            )
            row = cursor.fetchone()
            return self._row_to_record(row) if row else None
    
    def list_all(self) -> List[SongRecord]:
        """列出所有记录"""
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM songs ORDER BY artist, title")
            return [self._row_to_record(row) for row in cursor.fetchall()]
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息（使用 SQL 聚合查询）"""
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            
            # 总数
            cursor = conn.execute("SELECT COUNT(*) as total FROM songs")
            total = cursor.fetchone()['total']
            
            # 语言统计
            cursor = conn.execute(
                "SELECT language, COUNT(*) as cnt FROM songs WHERE language != '' GROUP BY language ORDER BY cnt DESC"
            )
            lang_stats = {row['language']: row['cnt'] for row in cursor.fetchall()}
            
            # 情绪统计
            cursor = conn.execute(
                "SELECT emotion, COUNT(*) as cnt FROM songs WHERE emotion != '' GROUP BY emotion ORDER BY cnt DESC"
            )
            emotion_stats = {row['emotion']: row['cnt'] for row in cursor.fetchall()}
            
            # 流派统计
            cursor = conn.execute(
                "SELECT genre, COUNT(*) as cnt FROM songs WHERE genre != '' GROUP BY genre ORDER BY cnt DESC"
            )
            genre_stats = {row['genre']: row['cnt'] for row in cursor.fetchall()}
            
            # 歌词统计
            cursor = conn.execute(
                "SELECT COUNT(*) as cnt FROM songs WHERE has_lyrics = '是'"
            )
            lyrics_count = cursor.fetchone()['cnt']
        
        return {
            'total': total,
            'languages': lang_stats,
            'emotions': emotion_stats,
            'genres': genre_stats,
            'lyrics_count': lyrics_count
        }
    
    def export_to_csv(self) -> str:
        """导出为CSV文件（可用Excel编辑）"""
        try:
            self.csv_file.parent.mkdir(parents=True, exist_ok=True)
            
            records = self.list_all()
            
            with open(self.csv_file, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                
                writer.writerow([
                    '艺术家', '标题', '专辑', '流派', '年份', '时长(秒)',
                    '语言', '语言来源', '情绪', '情绪置信度',
                    '有歌词', '歌词来源', '播放次数', '最后播放',
                    '用户备注', '文件路径', '更新时间'
                ])
                
                for record in records:
                    writer.writerow([
                        record.artist, record.title, record.album, record.genre,
                        record.year, record.duration, record.language, record.language_source,
                        record.emotion, record.emotion_confidence, record.has_lyrics,
                        record.lyrics_source, record.play_count, record.last_played,
                        record.notes, record.file_path, record.updated_at
                    ])
            
            return str(self.csv_file)
            
        except Exception as e:
            print(f"[ERROR] 导出CSV失败: {e}")
            return ""
    
    def delete(self, song_id: str) -> bool:
        """删除单条记录"""
        try:
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.execute("DELETE FROM songs WHERE id = ?", (song_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"[WARN] 删除记录失败: {e}")
            return False
    
    def delete_by_file_path(self, file_path: str) -> bool:
        """根据文件路径删除记录"""
        song_id = self._file_to_id(file_path)
        return self.delete(song_id)
    
    def import_from_csv(self, csv_path: str = None) -> int:
        """从CSV导入修改"""
        csv_path = csv_path or self.csv_file
        
        if not Path(csv_path).exists():
            print(f"[WARN] CSV文件不存在: {csv_path}")
            return 0
        
        updated = 0
        try:
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    artist = row.get('艺术家', '')
                    title = row.get('标题', '')
                    file_path = row.get('文件路径', '')
                    
                    if not artist or not title:
                        continue
                    
                    # 查询是否已存在
                    existing = self.get_record(artist, title)
                    
                    if existing:
                        # 更新可编辑字段
                        song_id = self._file_to_id(existing.file_path)
                        updates = {'updated_at': datetime.now().isoformat()}
                        if row.get('语言'): updates['language'] = row['语言']
                        if row.get('情绪'): updates['emotion'] = row['情绪']
                        if row.get('用户备注'): updates['notes'] = row['用户备注']
                        if row.get('播放次数'): updates['play_count'] = row['播放次数']
                        
                        set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
                        values = list(updates.values()) + [song_id]
                        
                        with sqlite3.connect(self.db_file) as conn:
                            conn.execute(f"UPDATE songs SET {set_clause} WHERE id = ?", values)
                            conn.commit()
                    else:
                        # 新记录
                        record = SongRecord(
                            file_path=file_path or '',
                            title=title,
                            artist=artist,
                            album=row.get('专辑', ''),
                            genre=row.get('流派', ''),
                            year=row.get('年份', ''),
                            duration=row.get('时长(秒)', ''),
                            language=row.get('语言', ''),
                            emotion=row.get('情绪', ''),
                            notes=row.get('用户备注', ''),
                            updated_at=datetime.now().isoformat()
                        )
                        self._insert_or_replace_record(record)
                    
                    updated += 1
            
            return updated
            
        except Exception as e:
            print(f"[ERROR] 导入CSV失败: {e}")
            return 0
    
    def migrate_from_chroma(self, vector_store):
        """从 ChromaDB 迁移数据到 SQLite（一次性）"""
        try:
            docs = vector_store.get_all()
            if not docs:
                return 0
            
            migrated = 0
            for doc in docs:
                meta = doc.get("metadata", {})
                file_path = meta.get("file_path", "")
                if not file_path:
                    continue
                
                record = SongRecord(
                    file_path=file_path,
                    title=meta.get("title", Path(file_path).stem),
                    artist=meta.get("artist", "Unknown"),
                    album=meta.get("album", ""),
                    genre=meta.get("genre", ""),
                    created_at=datetime.now().isoformat(),
                    updated_at=datetime.now().isoformat()
                )
                self._insert_or_replace_record(record)
                migrated += 1
            
            print(f"[MusicLibraryDB] 已从 ChromaDB 迁移 {migrated} 条记录到 SQLite")
            return migrated
            
        except Exception as e:
            print(f"[WARN] ChromaDB 迁移失败: {e}")
            return 0


# 单例
_db_instance = None

def get_library_db() -> MusicLibraryDB:
    """获取数据库单例"""
    global _db_instance
    if _db_instance is None:
        _db_instance = MusicLibraryDB()
    return _db_instance
