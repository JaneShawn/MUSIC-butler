"""
Smart Playlist Engine - NL query → multi-dimension filter → .m3u8 playlist
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from core.kimi_client import KimiClient
from core.playlist_manager import Playlist
from core.music_library_db import get_library_db
from core.emotion_constants import SPEED_KEYWORD_MAP, EMOTION_KEYWORDS
from core.language_constants import LANGUAGE_ALIAS
from core.logging_config import get_logger

logger = get_logger(__name__)


class SmartPlaylistEngine:
    """Natural language → structured query → playlist (.m3u8)"""

    def __init__(self, librarian=None, kimi_client=None):
        self.librarian = librarian
        self.kimi = kimi_client

    # ============================================================
    # Intent parsing
    # ============================================================

    def parse_intent(self, query_text: str) -> Dict[str, Any]:
        """
        Parse natural language into structured query intent.
        Applies local keyword fallback for speed/tempo terms before calling LLM.
        """
        original = query_text.strip()
        enhanced = self._apply_speed_keywords(original)

        # If we have Kimi, use it for full intent parsing
        intent = {}
        if self.kimi:
            try:
                intent = self.kimi.analyze_query_intent(enhanced or original)
            except Exception as e:
                logger.warning(f"Kimi intent parse failed: {e}")

        # Fallback: extract keywords locally
        if not intent or not any(v for k, v in intent.items() if k != "original_query"):
            intent = self._local_parse(original)

        intent["original_query"] = original
        intent["enhanced_query"] = enhanced if enhanced != original else original
        return intent

    def _apply_speed_keywords(self, text: str) -> str:
        """Replace speed/tempo keywords with emotion equivalents for better LLM parsing."""
        result = text
        for keyword, emotion_words in SPEED_KEYWORD_MAP.items():
            if keyword in result:
                result = result.replace(keyword, emotion_words)
                break  # Only apply the first match to avoid over-transforming
        if result != text:
            logger.debug(f"速度关键词映射: '{text}' → '{result}'")
        return result

    def _local_parse(self, text: str) -> Dict[str, Any]:
        """Local keyword-based fallback when Kimi is unavailable."""
        intent = {}
        text_lower = text.lower()

        for kw, emotion in EMOTION_KEYWORDS.items():
            if kw in text:
                intent["mood"] = emotion
                break

        for kw, lang in LANGUAGE_ALIAS.items():
            if kw in text:
                intent["language"] = lang
                break

        genre_map = {
            "摇滚": "摇滚", "流行": "流行", "说唱": "说唱", "嘻哈": "嘻哈",
            "爵士": "爵士", "电子": "电子", "民谣": "民谣", "古典": "古典",
            "R&B": "R&B", "r&b": "R&B",
        }
        for kw, genre in genre_map.items():
            if kw in text_lower:
                intent["genre"] = genre
                break

        return intent

    # ============================================================
    # Query execution
    # ============================================================

    def execute_query(self, intent: Dict, top_k: int = 50,
                      filters: Dict = None) -> List[Dict]:
        """
        Execute multi-dimension filtered query.
        Uses librarian.query() for semantic search + DB methods for precise filtering.

        Returns list of song dicts: {file_path, title, artist, album, genre, duration}
        """
        query_text = intent.get("enhanced_query") or intent.get("original_query", "")

        # Start with librarian's query (handles intent-aware filtering)
        results = []
        if self.librarian and query_text:
            raw = self.librarian.query(query_text, top_k=top_k, use_threshold=False)
            results = [r for r in raw if r.get("song")]

        # Collect songs
        songs = []
        seen = set()
        for r in results:
            song = r.get("song")
            if not song:
                continue
            key = song.file_path
            if key in seen:
                continue
            seen.add(key)
            songs.append({
                "file_path": song.file_path,
                "title": song.title or Path(song.file_path).stem,
                "artist": song.artist or "Unknown",
                "album": song.album or "",
                "duration": int(song.duration) if song.duration else 240,
                "genre": song.genre or "",
            })

        # Supplement with DB-based filtering for language and emotion
        lib_db = get_library_db()
        language = intent.get("language")
        emotion = intent.get("mood")

        if language and len(songs) < top_k:
            db_songs = lib_db.get_by_language(language, limit=top_k)
            for rec in db_songs:
                key = rec.file_path
                if key in seen:
                    continue
                seen.add(key)
                songs.append({
                    "file_path": rec.file_path,
                    "title": rec.title,
                    "artist": rec.artist,
                    "album": rec.album,
                    "duration": int(rec.duration) if rec.duration else 240,
                    "genre": rec.genre,
                })

        if emotion and len(songs) < top_k:
            db_songs = lib_db.get_by_emotion(emotion, limit=top_k)
            for rec in db_songs:
                key = rec.file_path
                if key in seen:
                    continue
                seen.add(key)
                songs.append({
                    "file_path": rec.file_path,
                    "title": rec.title,
                    "artist": rec.artist,
                    "album": rec.album,
                    "duration": int(rec.duration) if rec.duration else 240,
                    "genre": rec.genre,
                })

        # Apply extra filters from caller
        if filters:
            songs = self._apply_filters(songs, filters)

        return songs

    def _apply_filters(self, songs: List[Dict], filters: Dict) -> List[Dict]:
        """Apply post-query filters to song list."""
        if filters.get("artist"):
            artist_filter = filters["artist"].lower()
            songs = [s for s in songs if artist_filter in s.get("artist", "").lower()]

        if filters.get("genre"):
            genre_filter = filters["genre"].lower()
            songs = [s for s in songs if genre_filter in s.get("genre", "").lower()]

        if filters.get("year"):
            year_filter = str(filters["year"])
            # Simple substring match on year
            songs = [s for s in songs if year_filter in str(s.get("year", ""))]

        if filters.get("min_duration"):
            min_dur = int(filters["min_duration"])
            songs = [s for s in songs if s.get("duration", 0) >= min_dur]

        if filters.get("max_duration"):
            max_dur = int(filters["max_duration"])
            songs = [s for s in songs if s.get("duration", 0) <= max_dur]

        return songs

    # ============================================================
    # Playlist creation
    # ============================================================

    def create_playlist(self, query_text: str, name: str = None,
                        is_dynamic: bool = False,
                        output_dir: str = "playlists") -> Dict:
        """
        Create a smart playlist from natural language query.

        Returns {playlist_id, name, song_count, m3u8_path, songs}
        """
        intent = self.parse_intent(query_text)
        songs = self.execute_query(intent)

        if not name:
            name = query_text[:40].strip() or "智能歌单"

        # Generate .m3u8
        playlist = Playlist(
            name=name,
            songs=songs,
            criteria=intent,
            created_at=datetime.now(),
        )
        m3u8_path = playlist.save(output_dir)

        # Persist to DB
        criteria_json = json.dumps(intent, ensure_ascii=False)
        lib_db = get_library_db()
        playlist_id = lib_db.create_playlist(
            name=name,
            query_text=query_text,
            parsed_intent=json.dumps(intent, ensure_ascii=False),
            criteria=criteria_json,
            is_dynamic=is_dynamic,
            songs=songs,
            m3u8_path=m3u8_path,
        )

        return {
            "playlist_id": playlist_id,
            "name": name,
            "song_count": len(songs),
            "m3u8_path": m3u8_path,
            "songs": songs,
            "intent": intent,
            "is_dynamic": is_dynamic,
        }

    def refresh_dynamic_playlist(self, playlist_id: int) -> Optional[Dict]:
        """
        Re-execute the query for a dynamic playlist and update songs.
        """
        lib_db = get_library_db()
        pl = lib_db.get_playlist(playlist_id)
        if not pl:
            logger.warning(f"Playlist {playlist_id} not found")
            return None

        query_text = pl.get("query_text", "")
        intent = self.parse_intent(query_text)
        songs = self.execute_query(intent)

        lib_db.refresh_playlist_songs(playlist_id, songs)

        # Re-generate .m3u8
        playlist = Playlist(
            name=pl.get("name", "动态歌单"),
            songs=songs,
            criteria=intent,
            created_at=datetime.now(),
        )
        m3u8_path = playlist.save("playlists")

        return {
            "playlist_id": playlist_id,
            "name": pl.get("name"),
            "song_count": len(songs),
            "m3u8_path": m3u8_path,
            "songs": songs,
            "intent": intent,
            "is_dynamic": True,
        }

    def list_playlists(self) -> List[Dict]:
        return get_library_db().list_playlists()

    def get_playlist(self, playlist_id: int) -> Optional[Dict]:
        return get_library_db().get_playlist(playlist_id)

    def delete_playlist(self, playlist_id: int) -> bool:
        return get_library_db().delete_playlist(playlist_id)
