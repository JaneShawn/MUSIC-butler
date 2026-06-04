# -*- coding: utf-8 -*-
"""
音乐库数据库 - SQLite 版
管理所有歌曲的完整信息，支持导出为CSV，可用Excel编辑
"""

from core.logging_config import get_logger
logger = get_logger(__name__)

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
    has_lyrics_int: int = 0  # 1=有歌词, 0=无歌词（整数，替代文本字段）
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
    'has_lyrics', 'has_lyrics_int', 'lyrics_source', 'play_count', 'last_played', 'notes',
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
                    has_lyrics_int INTEGER DEFAULT 0,
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
            # 兼容旧表：添加 has_lyrics_int 列
            try:
                conn.execute("ALTER TABLE songs ADD COLUMN has_lyrics_int INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # 列已存在

            conn.execute("CREATE INDEX IF NOT EXISTS idx_has_lyrics_int ON songs(has_lyrics_int)")
            conn.commit()

            # 迁移旧 has_lyrics 文本 -> has_lyrics_int 整数
            self._migrate_has_lyrics_int(conn)

        # 创建新表（smart_playlists, smart_playlist_songs, metadata_fix_log）
        self._init_new_tables()

    def _migrate_has_lyrics_int(self, conn):
        """将 has_lyrics 文本字段迁移为 has_lyrics_int 整数字段"""
        cursor = conn.execute(
            "SELECT COUNT(*) FROM songs WHERE has_lyrics_int = 0 AND has_lyrics = '是'"
        )
        count = cursor.fetchone()[0]
        if count > 0:
            conn.execute(
                "UPDATE songs SET has_lyrics_int = 1 WHERE has_lyrics = '是' AND has_lyrics_int = 0"
            )
            conn.commit()
            logger.info(f"已迁移 {count} 条 has_lyrics 文本→整数")

    def _init_new_tables(self):
        """创建智能歌单和元数据修复日志表"""
        with sqlite3.connect(self.db_file) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS smart_playlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    query_text TEXT NOT NULL,
                    parsed_intent TEXT DEFAULT '',
                    criteria TEXT DEFAULT '{}',
                    is_dynamic INTEGER DEFAULT 0,
                    song_count INTEGER DEFAULT 0,
                    m3u8_path TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS smart_playlist_songs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    playlist_id INTEGER NOT NULL,
                    song_db_id TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    artist TEXT DEFAULT '',
                    title TEXT DEFAULT '',
                    sort_order INTEGER DEFAULT 0,
                    added_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (playlist_id) REFERENCES smart_playlists(id) ON DELETE CASCADE,
                    FOREIGN KEY (song_db_id) REFERENCES songs(id) ON DELETE CASCADE
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metadata_fix_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT NOT NULL,
                    song_id TEXT DEFAULT '',
                    fix_type TEXT NOT NULL,
                    old_value TEXT DEFAULT '',
                    new_value TEXT DEFAULT '',
                    status TEXT DEFAULT 'success',
                    error_msg TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_playlist_id ON smart_playlist_songs(playlist_id)")
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
            
            logger.info(f"已从 JSON 迁移 {migrated} 条记录到 SQLite")
            
            # 迁移完成后重命名旧文件，避免重复迁移
            json_file.rename(json_file.with_suffix('.json.bak'))
            
        except Exception as e:
            logger.warning(f"JSON 迁移失败: {e}")
    
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
            has_lyrics_int=int(row['has_lyrics_int']) if row['has_lyrics_int'] else 0,
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
                    has_lyrics, has_lyrics_int, lyrics_source, play_count, last_played, notes,
                    updated_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                song_id, record.file_path, record.title, record.artist,
                record.album, record.genre, record.year, record.duration,
                record.language, record.language_source, record.emotion,
                record.emotion_confidence, record.has_lyrics, record.has_lyrics_int,
                record.lyrics_source,
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
        flag_int = 1 if has_lyrics else 0
        with sqlite3.connect(self.db_file) as conn:
            conn.execute(
                """UPDATE songs SET has_lyrics = ?, has_lyrics_int = ?, lyrics_source = ?, updated_at = ?
                   WHERE artist = ? AND title = ?""",
                (flag, flag_int, source, datetime.now().isoformat(), artist, title)
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
    
    def list_artists(self) -> List[str]:
        """返回所有不重复的艺术家名（排除 Unknown）。"""
        with sqlite3.connect(self.db_file) as conn:
            rows = conn.execute(
                "SELECT DISTINCT artist FROM songs WHERE artist != 'Unknown' AND artist != '' ORDER BY artist"
            ).fetchall()
            return [r[0] for r in rows]

    def list_albums(self) -> List[str]:
        """返回所有不重复的专辑名（排除 Unknown）。"""
        with sqlite3.connect(self.db_file) as conn:
            rows = conn.execute(
                "SELECT DISTINCT album FROM songs WHERE album != 'Unknown' AND album != '' ORDER BY album"
            ).fetchall()
            return [r[0] for r in rows]

    def list_genres(self) -> List[str]:
        """返回所有不重复的流派名。"""
        with sqlite3.connect(self.db_file) as conn:
            rows = conn.execute(
                "SELECT DISTINCT genre FROM songs WHERE genre != '' ORDER BY genre"
            ).fetchall()
            return [r[0] for r in rows]

    def list_languages(self) -> List[str]:
        """返回所有不重复的语言标签。"""
        with sqlite3.connect(self.db_file) as conn:
            rows = conn.execute(
                "SELECT DISTINCT language FROM songs WHERE language != '' ORDER BY language"
            ).fetchall()
            return [r[0] for r in rows]

    def list_emotions(self) -> List[str]:
        """返回所有不重复的情绪标签。"""
        with sqlite3.connect(self.db_file) as conn:
            rows = conn.execute(
                "SELECT DISTINCT emotion FROM songs WHERE emotion != '' ORDER BY emotion"
            ).fetchall()
            return [r[0] for r in rows]

    def filter_songs(
        self,
        artist: str = None,
        album: str = None,
        genre: str = None,
        language: str = None,
        emotion: str = None,
        search: str = None,
        sort_by: str = "artist",
        limit: int = 500,
    ) -> List[SongRecord]:
        """多条件组合筛选歌曲。

        Args:
            artist: 精确匹配艺术家名
            album: 精确匹配专辑名
            genre: 精确匹配流派
            language: 精确匹配语言
            emotion: 精确匹配情绪
            search: 模糊搜索（匹配 title 或 artist）
            sort_by: 排序字段 (artist, title, album, year, play_count)
            limit: 最大返回数
        """
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        conditions = []
        params = []

        if artist:
            conditions.append("artist = ?")
            params.append(artist)
        if album:
            conditions.append("album = ?")
            params.append(album)
        if genre:
            conditions.append("genre = ?")
            params.append(genre)
        if language:
            conditions.append("language = ?")
            params.append(language)
        if emotion:
            conditions.append("emotion = ?")
            params.append(emotion)
        if search:
            conditions.append("(title LIKE ? OR artist LIKE ?)")
            kw = f"%{search}%"
            params.extend([kw, kw])

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        valid_sorts = {"artist", "title", "album", "year", "play_count"}
        order = sort_by if sort_by in valid_sorts else "artist"

        rows = conn.execute(
            f"SELECT * FROM songs{where} ORDER BY {order} LIMIT ?",
            params + [limit],
        ).fetchall()
        conn.close()
        return [self._row_to_record(r) for r in rows]

    def update_song_fields(self, artist: str, title: str, **fields) -> bool:
        """更新一首歌的任意字段。

        可更新的字段: language, emotion, genre, album, year, notes
        例: update_song_fields('周杰伦', '晴天', language='国语', emotion='happy')
        """
        allowed = {"language", "emotion", "genre", "album", "year", "notes",
                   "language_source", "emotion_confidence"}
        updates = {k: v for k, v in fields.items() if k in allowed and v}
        if not updates:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [artist, title]
        with sqlite3.connect(self.db_file) as conn:
            cur = conn.execute(
                f"UPDATE songs SET {set_clause} WHERE artist = ? AND title = ?",
                values,
            )
            conn.commit()
            return cur.rowcount > 0

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
            logger.error(f"导出CSV失败: {e}")
            return ""
    
    def delete(self, song_id: str) -> bool:
        """删除单条记录"""
        try:
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.execute("DELETE FROM songs WHERE id = ?", (song_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.warning(f"删除记录失败: {e}")
            return False
    
    def delete_by_file_path(self, file_path: str) -> bool:
        """根据文件路径删除记录"""
        song_id = self._file_to_id(file_path)
        return self.delete(song_id)
    
    def import_from_csv(self, csv_path: str = None) -> int:
        """从CSV导入修改"""
        csv_path = csv_path or self.csv_file
        
        if not Path(csv_path).exists():
            logger.warning(f"CSV文件不存在: {csv_path}")
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
            logger.error(f"导入CSV失败: {e}")
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
            
            logger.info(f"已从 ChromaDB 迁移 {migrated} 条记录到 SQLite")
            return migrated
            
        except Exception as e:
            logger.warning(f"ChromaDB 迁移失败: {e}")
            return 0

    # ============================================================
    # 新增方法：情绪批量更新、诊断、查询
    # ============================================================

    def batch_update_emotion(self, emotion_map: Dict[str, Dict]) -> int:
        """
        批量更新歌曲情绪信息

        Args:
            emotion_map: {file_path_hash: {"emotion": str, "confidence": float, "source": str}}
        Returns:
            更新数量
        """
        updated = 0
        with sqlite3.connect(self.db_file) as conn:
            for file_hash, info in emotion_map.items():
                emotion = info.get("emotion", "")
                confidence = str(info.get("confidence", ""))
                source = info.get("source", "")
                if not emotion:
                    continue
                # 通过 file_path 的 MD5 前缀匹配 song id
                cursor = conn.execute(
                    "UPDATE songs SET emotion = ?, emotion_confidence = ?, updated_at = ? "
                    "WHERE id LIKE ?",
                    (emotion, confidence, datetime.now().isoformat(), file_hash + "%")
                )
                updated += cursor.rowcount
            conn.commit()
        return updated

    def diagnose_incomplete(self) -> Dict[str, Any]:
        """
        诊断元数据不完整的歌曲

        Returns:
            {
                "total": 总歌曲数,
                "missing_artist": 数量,
                "missing_cover": 数量 (has_lyrics_int=0 的也算缺封面信号),
                "missing_emotion": 数量,
                "has_lyrics_issue": has_lyrics 文本字段残留 "是/否" 的数量,
                "songs_missing_artist": [file_path list],
                "songs_missing_emotion": [file_path list],
                "songs_has_lyrics_issue": [file_path list],
            }
        """
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row

            cursor = conn.execute("SELECT COUNT(*) as cnt FROM songs")
            total = cursor.fetchone()["cnt"]

            cursor = conn.execute(
                "SELECT COUNT(*) as cnt FROM songs WHERE artist = 'Unknown' OR artist = ''"
            )
            missing_artist = cursor.fetchone()["cnt"]

            cursor = conn.execute(
                "SELECT COUNT(*) as cnt FROM songs WHERE emotion = '' OR emotion IS NULL"
            )
            missing_emotion = cursor.fetchone()["cnt"]

            cursor = conn.execute(
                "SELECT COUNT(*) as cnt FROM songs WHERE has_lyrics = '是' AND has_lyrics_int = 0"
            )
            has_lyrics_issue = cursor.fetchone()["cnt"]

            # 取样本列表
            cursor = conn.execute(
                "SELECT file_path FROM songs WHERE artist = 'Unknown' OR artist = '' LIMIT 100"
            )
            songs_missing_artist = [r["file_path"] for r in cursor.fetchall()]

            cursor = conn.execute(
                "SELECT file_path FROM songs WHERE emotion = '' OR emotion IS NULL LIMIT 100"
            )
            songs_missing_emotion = [r["file_path"] for r in cursor.fetchall()]

            cursor = conn.execute(
                "SELECT file_path FROM songs WHERE has_lyrics = '是' AND has_lyrics_int = 0 LIMIT 100"
            )
            songs_has_lyrics_issue = [r["file_path"] for r in cursor.fetchall()]

        return {
            "total": total,
            "missing_artist": missing_artist,
            "missing_emotion": missing_emotion,
            "has_lyrics_issue": has_lyrics_issue,
            "songs_missing_artist": songs_missing_artist,
            "songs_missing_emotion": songs_missing_emotion,
            "songs_has_lyrics_issue": songs_has_lyrics_issue,
        }

    def get_by_emotion(self, emotion: str, limit: int = 100) -> List[SongRecord]:
        """根据情绪标签获取歌曲"""
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM songs WHERE emotion = ? LIMIT ?",
                (emotion, limit)
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def get_by_language(self, language: str, limit: int = 100) -> List[SongRecord]:
        """根据语言获取歌曲"""
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM songs WHERE language = ? LIMIT ?",
                (language, limit)
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def fix_has_lyrics_field(self) -> int:
        """将 has_lyrics 文本 '是'/'否' 迁移到 has_lyrics_int 1/0，修复残留数据"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.execute(
                "UPDATE songs SET has_lyrics_int = 1 WHERE has_lyrics = '是' AND has_lyrics_int = 0"
            )
            fixed = cursor.rowcount
            conn.commit()
            if fixed:
                logger.info(f"has_lyrics 文本→整数修复: {fixed} 条")
            return fixed

    # ============================================================
    # 智能歌单 CRUD
    # ============================================================

    def create_playlist(self, name: str, query_text: str, parsed_intent: str = "",
                        criteria: str = "{}", is_dynamic: bool = False,
                        songs: List[Dict] = None, m3u8_path: str = "") -> int:
        """创建智能歌单，返回 playlist_id"""
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.execute(
                """INSERT INTO smart_playlists (name, description, query_text, parsed_intent,
                   criteria, is_dynamic, song_count, m3u8_path, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, "", query_text, parsed_intent, criteria,
                 1 if is_dynamic else 0, len(songs) if songs else 0,
                 m3u8_path, now, now)
            )
            playlist_id = cursor.lastrowid

            if songs:
                for idx, song in enumerate(songs):
                    song_id = self._file_to_id(song.get("file_path", ""))
                    conn.execute(
                        """INSERT INTO smart_playlist_songs
                           (playlist_id, song_db_id, file_path, artist, title, sort_order)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (playlist_id, song_id, song.get("file_path", ""),
                         song.get("artist", ""), song.get("title", ""), idx)
                    )
            conn.commit()
        return playlist_id

    def get_playlist(self, playlist_id: int) -> Optional[Dict]:
        """获取单个智能歌单及其歌曲"""
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM smart_playlists WHERE id = ?", (playlist_id,)
            )
            pl = cursor.fetchone()
            if not pl:
                return None

            cursor = conn.execute(
                "SELECT * FROM smart_playlist_songs WHERE playlist_id = ? ORDER BY sort_order",
                (playlist_id,)
            )
            songs = [dict(r) for r in cursor.fetchall()]

            result = dict(pl)
            result["songs"] = songs
            return result

    def list_playlists(self) -> List[Dict]:
        """列出所有智能歌单"""
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM smart_playlists ORDER BY updated_at DESC"
            )
            return [dict(r) for r in cursor.fetchall()]

    def delete_playlist(self, playlist_id: int) -> bool:
        """删除智能歌单及其歌曲"""
        with sqlite3.connect(self.db_file) as conn:
            conn.execute("DELETE FROM smart_playlist_songs WHERE playlist_id = ?", (playlist_id,))
            cursor = conn.execute("DELETE FROM smart_playlists WHERE id = ?", (playlist_id,))
            conn.commit()
            return cursor.rowcount > 0

    def refresh_playlist_songs(self, playlist_id: int, songs: List[Dict]) -> bool:
        """刷新动态歌单的歌曲列表"""
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_file) as conn:
            conn.execute(
                "DELETE FROM smart_playlist_songs WHERE playlist_id = ?", (playlist_id,)
            )
            for idx, song in enumerate(songs):
                song_id = self._file_to_id(song.get("file_path", ""))
                conn.execute(
                    """INSERT INTO smart_playlist_songs
                       (playlist_id, song_db_id, file_path, artist, title, sort_order)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (playlist_id, song_id, song.get("file_path", ""),
                     song.get("artist", ""), song.get("title", ""), idx)
                )
            conn.execute(
                "UPDATE smart_playlists SET song_count = ?, updated_at = ? WHERE id = ?",
                (len(songs), now, playlist_id)
            )
            conn.commit()
        return True

    def add_song_to_playlist(self, playlist_id: int, artist: str, title: str,
                             file_path: str = "") -> bool:
        """手动添加一首歌到歌单。"""
        with sqlite3.connect(self.db_file) as conn:
            # 获取当前最大 sort_order
            row = conn.execute(
                "SELECT MAX(sort_order) FROM smart_playlist_songs WHERE playlist_id = ?",
                (playlist_id,)
            ).fetchone()
            next_order = (row[0] or 0) + 1
            conn.execute(
                """INSERT INTO smart_playlist_songs
                   (playlist_id, file_path, artist, title, sort_order)
                   VALUES (?, ?, ?, ?, ?)""",
                (playlist_id, file_path, artist, title, next_order),
            )
            conn.execute(
                "UPDATE smart_playlists SET song_count = song_count + 1, updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), playlist_id),
            )
            conn.commit()
        return True

    def remove_song_from_playlist(self, playlist_id: int, artist: str, title: str) -> bool:
        """从歌单中移除一首歌。"""
        with sqlite3.connect(self.db_file) as conn:
            cur = conn.execute(
                "DELETE FROM smart_playlist_songs WHERE playlist_id = ? AND artist = ? AND title = ?",
                (playlist_id, artist, title),
            )
            if cur.rowcount > 0:
                conn.execute(
                    "UPDATE smart_playlists SET song_count = MAX(0, song_count - 1), updated_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), playlist_id),
                )
            conn.commit()
            return cur.rowcount > 0

    def log_metadata_fix(self, file_path: str, fix_type: str, old_value: str = "",
                         new_value: str = "", status: str = "success", error_msg: str = ""):
        """记录元数据修复操作"""
        song_id = self._file_to_id(file_path) if file_path else ""
        with sqlite3.connect(self.db_file) as conn:
            conn.execute(
                """INSERT INTO metadata_fix_log (file_path, song_id, fix_type, old_value,
                   new_value, status, error_msg) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (file_path, song_id, fix_type, old_value, new_value, status, error_msg)
            )
            conn.commit()

    def get_fix_log(self, limit: int = 50) -> List[Dict]:
        """获取最近的修复日志"""
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM metadata_fix_log ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
            return [dict(r) for r in cursor.fetchall()]


# 单例
_db_instance = None

def get_library_db() -> MusicLibraryDB:
    """获取数据库单例"""
    global _db_instance
    if _db_instance is None:
        _db_instance = MusicLibraryDB()
    return _db_instance
