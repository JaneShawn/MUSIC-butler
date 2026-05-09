"""
Folder Watcher - watchdog-based real-time filesystem monitoring
Monitors MUSIC/ and ALBUM/ directories for add/delete events with 3s debounce.
"""
import threading
import time
from pathlib import Path
from typing import Optional, Set, Callable

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from core.logging_config import get_logger
from core.music_library_db import get_library_db

logger = get_logger(__name__)

DEBOUNCE_SECONDS = 3
WATCH_EXTENSIONS = {".flac", ".mp3", ".wav", ".m4a", ".ogg"}


class MusicFileHandler(FileSystemEventHandler):
    """Collects file events and debounces into batches."""

    def __init__(self, on_change: Callable):
        super().__init__()
        self._on_change = on_change
        self._pending: Set[str] = set()
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def _is_music_file(self, path: str) -> bool:
        return Path(path).suffix.lower() in WATCH_EXTENSIONS

    def _schedule_flush(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(DEBOUNCE_SECONDS, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self):
        with self._lock:
            if not self._pending:
                return
            paths = list(self._pending)
            self._pending.clear()
            self._timer = None
        self._on_change(paths)

    def on_created(self, event: FileSystemEvent):
        if not event.is_directory and self._is_music_file(event.src_path):
            with self._lock:
                self._pending.add(event.src_path)
            self._schedule_flush()

    def on_deleted(self, event: FileSystemEvent):
        if not event.is_directory and self._is_music_file(event.src_path):
            with self._lock:
                self._pending.add(event.src_path)
            self._schedule_flush()


class FolderWatcher:
    """Watchdog-based folder monitor with start/stop control."""

    def __init__(self, watch_dirs: list = None):
        self._watch_dirs = watch_dirs or []
        self._observer: Optional[Observer] = None
        self._handler: Optional[MusicFileHandler] = None
        self._running = False
        self._librarian = None  # set via set_librarian()

    def set_librarian(self, librarian):
        self._librarian = librarian

    @property
    def is_running(self) -> bool:
        return self._running

    def _on_files_changed(self, paths: list):
        """Called after debounce window with aggregated file paths."""
        if not self._librarian:
            return

        lib_db = get_library_db()
        added = []
        deleted = []
        for p in paths:
            if Path(p).exists():
                added.append(p)
            else:
                deleted.append(p)

        if added:
            logger.info(f"检测到 {len(added)} 个新文件，触发扫描")
            try:
                result = self._librarian.run("scan")
                logger.info(f"扫描完成: 新增 {result.get('new_songs', 0)} 首")
            except Exception as e:
                logger.error(f"扫描失败: {e}")

        if deleted:
            logger.info(f"检测到 {len(deleted)} 个文件被删除，清理索引")
            for fp in deleted:
                song_id = self._librarian._file_to_id(fp)
                try:
                    self._librarian.vector_store.delete(song_id)
                except Exception:
                    pass
                lib_db.delete_by_file_path(fp)
                if song_id in self._librarian.songs:
                    del self._librarian.songs[song_id]
            logger.info(f"已清理 {len(deleted)} 条残留索引")

    def start(self):
        if self._running:
            return
        if not self._watch_dirs:
            logger.info("未配置监控目录，跳过")
            return

        # 确保所有目录存在
        valid_dirs = []
        for d in self._watch_dirs:
            p = Path(d)
            if p.exists() and p.is_dir():
                valid_dirs.append(str(p.resolve()))
            else:
                logger.info(f"目录不存在，跳过监控: {d}")

        if not valid_dirs:
            logger.info("无有效监控目录")
            return

        self._handler = MusicFileHandler(self._on_files_changed)
        self._observer = Observer()

        for d in valid_dirs:
            self._observer.schedule(self._handler, d, recursive=True)
            logger.info(f"开始监控: {d}")

        self._observer.daemon = True
        self._observer.start()
        self._running = True
        logger.info("实时监控已启动")

    def stop(self):
        if not self._running:
            return
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        self._handler = None
        self._running = False
        logger.info("实时监控已停止")

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "watch_dirs": self._watch_dirs,
        }
