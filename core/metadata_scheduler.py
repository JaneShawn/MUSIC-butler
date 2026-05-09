"""
Metadata Scheduler - emotion cache sync, metadata diagnosis, batch fix
"""
import json
import hashlib
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any

from core.logging_config import get_logger
from core.music_library_db import get_library_db

logger = get_logger(__name__)


class MetadataScheduler:
    """Batch metadata maintenance: emotion sync, diagnosis, fix."""

    def __init__(self, metadata_enhancer=None, librarian=None):
        self.enhancer = metadata_enhancer
        self.librarian = librarian
        self._cache_file = Path("data/emotion_cache.json")

    # ============================================================
    # Emotion cache sync
    # ============================================================

    def sync_emotion_cache(self) -> int:
        """
        Read data/emotion_cache.json and batch-write emotion fields to SQLite.

        Cache key: md5(file_path:mtime)[:16] (from AudioEmotionAnalyzer._get_file_hash)
        Cache value: {"emotion": str, "confidence": float, "source": str, ...}

        Returns number of songs updated.
        """
        if not self._cache_file.exists():
            logger.info("emotion_cache.json not found, skipping sync")
            return 0

        with open(self._cache_file, "r", encoding="utf-8") as f:
            cache = json.load(f)

        if not cache:
            return 0

        lib_db = get_library_db()
        all_songs = lib_db.list_all()

        # Build lookup: computed_hash → SongRecord
        hash_to_song = {}
        for song in all_songs:
            fp = song.file_path
            if not fp or not os.path.exists(fp):
                continue
            try:
                mtime = os.path.getmtime(fp)
                h = hashlib.md5(f"{fp}:{mtime}".encode()).hexdigest()[:16]
                hash_to_song[h] = song
            except OSError:
                continue

        # Match cache entries to songs and update
        updated = 0
        for file_hash, info in cache.items():
            song = hash_to_song.get(file_hash)
            if not song:
                continue
            emotion = info.get("emotion", "")
            confidence = str(info.get("confidence", ""))
            source = info.get("source", "")
            if not emotion:
                continue

            lib_db.update_emotion(song.artist, song.title, emotion, confidence)
            # Also store source in emotion_confidence field or notes if needed
            updated += 1

        logger.info(f"emotion_cache → SQLite: {updated} 首已同步")
        return updated

    # ============================================================
    # Diagnosis
    # ============================================================

    def diagnose(self) -> Dict[str, Any]:
        """
        Find songs with incomplete metadata.

        Returns dict with issue counts and sample file paths.
        """
        lib_db = get_library_db()
        result = lib_db.diagnose_incomplete()

        # Also check for songs without artist (via librarian's in-memory list)
        missing_cover = 0
        if self.librarian:
            for song in self.librarian.songs.values():
                if song.artist == "Unknown" or not song.artist:
                    missing_cover += 1

        result["missing_cover_signal"] = missing_cover

        issue_count = (
            result.get("missing_artist", 0)
            + result.get("missing_emotion", 0)
            + result.get("has_lyrics_issue", 0)
            + missing_cover
        )
        result["total_issues"] = issue_count
        result["healthy"] = issue_count == 0

        return result

    # ============================================================
    # Preview / Execute fix
    # ============================================================

    def preview_fix(self) -> List[Dict]:
        """
        Preview what would be fixed (dry-run).
        Returns list of {file_path, issue_type, current_value}.
        """
        diag = self.diagnose()
        preview = []

        for fp in diag.get("songs_missing_artist", []):
            preview.append({"file_path": fp, "issue_type": "missing_artist", "current_value": "Unknown"})

        for fp in diag.get("songs_missing_emotion", []):
            preview.append({"file_path": fp, "issue_type": "missing_emotion", "current_value": ""})

        for fp in diag.get("songs_has_lyrics_issue", []):
            preview.append({"file_path": fp, "issue_type": "has_lyrics_text", "current_value": "是"})

        return preview

    def execute_fix(self, batch_size: int = 20, download_cover: bool = True) -> Dict:
        """
        Execute metadata fix using the librarian's fix_metadata().
        Also runs fix_has_lyrics_field() afterwards.

        Args:
            batch_size: songs per batch
            download_cover: whether to download covers
        """
        lib_db = get_library_db()

        # Fix has_lyrics field first
        lyrics_fixed = lib_db.fix_has_lyrics_field()

        # Fix metadata via librarian
        fix_result = {}
        if self.librarian:
            fix_result = self.librarian.fix_metadata(
                dry_run=False,
                rename_files=False,
                batch_size=batch_size,
                download_cover=download_cover,
            )

        # Log results
        total_fixed = fix_result.get("fixed", 0) if fix_result else 0
        if total_fixed > 0:
            for item in fix_result.get("results", []):
                lib_db.log_metadata_fix(
                    file_path=item.get("file", ""),
                    fix_type="metadata",
                    old_value=f"{item.get('old_artist', '')} - {item.get('old_title', '')}",
                    new_value=f"{item.get('new_artist', '')} - {item.get('new_title', '')}",
                    status="success",
                )

        return {
            "lyrics_field_fixed": lyrics_fixed,
            "metadata_fixed": total_fixed,
            "covers_embedded": fix_result.get("covers", 0) if fix_result else 0,
            "failed": fix_result.get("failed", 0) if fix_result else 0,
            "fix_result": fix_result,
        }

    def fix_has_lyrics_field(self) -> int:
        """Fix has_lyrics text '是'/'否' → integer 1/0."""
        return get_library_db().fix_has_lyrics_field()

    # ============================================================
    # Fix log
    # ============================================================

    def get_fix_history(self, limit: int = 50) -> List[Dict]:
        return get_library_db().get_fix_log(limit)
