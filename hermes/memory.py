# -*- coding: utf-8 -*-
"""
Hermes Memory — 结构化语义记忆存储

[Phase 6] Hybrid Memory: SQLite 精确匹配 + ChromaDB 语义检索。
Gateway 路由时查询相关记忆注入上下文。
记忆会在每次 Reflect 后自动更新，长期不用的记忆会衰减。
"""
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings


@dataclass
class Memory:
    """一条语义记忆"""
    id: int = 0
    mtype: str = ""             # "preference" | "fact" | "pattern" | "correction"
    key: str = ""               # 如 "like_artist:周杰伦"、"lang_preference:国语"
    value: str = ""             # 记忆内容
    confidence: float = 0.5     # 0-1，越高越可信
    source: str = ""            # 从哪次交互提取
    created_at: str = ""
    last_accessed: str = ""
    access_count: int = 0


class MemoryStore:
    """SQLite 记忆存储。

    使用方式:
        store = get_memory_store()
        store.upsert("preference", "like_artist", "周杰伦", confidence=0.8)
        memories = store.query_relevant("我想听歌")
    """

    def __init__(self, db_path: str = "data/hermes_memory.db"):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()
        self._init_chroma()

    def _init_db(self):
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mtype TEXT NOT NULL DEFAULT '',
                    key TEXT NOT NULL DEFAULT '',
                    value TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    source TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    last_accessed TEXT NOT NULL DEFAULT '',
                    access_count INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_mtype ON memories(mtype)
            """)
            conn.commit()

    def _init_chroma(self):
        """初始化 ChromaDB collection 用于语义记忆检索。"""
        try:
            chroma_dir = str(Path(self._db_path).parent / "chroma_memory")
            self._chroma_client = chromadb.PersistentClient(
                path=chroma_dir,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self._memory_collection = self._chroma_client.get_or_create_collection(
                name="hermes_memory",
                metadata={"hnsw:space": "cosine"},
            )
        except Exception:
            self._chroma_client = None
            self._memory_collection = None

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def upsert(self, mtype: str, key: str, value: str,
               confidence: float = 0.5, source: str = "") -> None:
        """插入或更新一条记忆。相同 key 会合并并提高置信度。
        同时写入 SQLite（精确匹配）和 ChromaDB（语义检索）。"""
        now = datetime.now().isoformat()
        with self._lock:
            with self._get_conn() as conn:
                existing = conn.execute(
                    "SELECT id, confidence, access_count FROM memories WHERE key = ?",
                    (key,)
                ).fetchone()

                if existing:
                    new_conf = max(confidence, existing["confidence"])
                    new_conf = (existing["confidence"] * existing["access_count"] + confidence) / (existing["access_count"] + 1)
                    conn.execute(
                        """UPDATE memories
                           SET value = ?, confidence = ?, source = ?,
                               last_accessed = ?, access_count = access_count + 1
                           WHERE id = ?""",
                        (value, new_conf, source, now, existing["id"])
                    )
                else:
                    conn.execute(
                        """INSERT INTO memories (mtype, key, value, confidence, source, created_at, last_accessed, access_count)
                           VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                        (mtype, key, value, confidence, source, now, now)
                    )
                conn.commit()

            # 同步写入 ChromaDB（语义检索）
            if self._memory_collection is not None:
                try:
                    doc = f"{key} {value}"
                    self._memory_collection.upsert(
                        documents=[doc],
                        ids=[key],
                    )
                except Exception:
                    pass

    def query_relevant(self, context: str, limit: int = 5) -> List[Memory]:
        """混合检索相关记忆：SQLite 精确匹配 + ChromaDB 语义检索。

        两路结果合并去重：
          - SQLite: 关键词包含匹配（保持精确 key 命中的优势）
          - ChromaDB: 语义相似检索（补上跨语义关联）
        """
        now = datetime.now().isoformat()
        words = [w for w in context.replace('，', ' ').replace(',', ' ').split()
                 if len(w) >= 1][:10]
        seen_keys: set = set()
        results: List[Memory] = []

        with self._lock:
            # 第一路: SQLite 精确匹配（按类型优先级 + 置信度排序）
            with self._get_conn() as conn:
                rows = conn.execute(
                    """SELECT * FROM memories
                       ORDER BY
                         CASE mtype
                           WHEN 'correction' THEN 1
                           WHEN 'preference' THEN 2
                           WHEN 'pattern' THEN 3
                           WHEN 'fact' THEN 4
                           ELSE 5
                         END,
                         confidence DESC,
                         access_count DESC
                       LIMIT ?""",
                    (limit * 3,)
                ).fetchall()

                for row in rows:
                    rkey = row["key"]
                    rval = row["value"]
                    if any(w in rkey or w in rval for w in words if len(w) >= 2):
                        mem = Memory(
                            id=row["id"], mtype=row["mtype"], key=rkey, value=rval,
                            confidence=row["confidence"], source=row["source"],
                            created_at=row["created_at"], last_accessed=row["last_accessed"],
                            access_count=row["access_count"],
                        )
                        results.append(mem)
                        seen_keys.add(rkey)

                # 更新 SQLite 命中记录的访问时间
                for m in results:
                    conn.execute(
                        "UPDATE memories SET last_accessed = ?, access_count = access_count + 1 WHERE id = ?",
                        (now, m.id)
                    )
                conn.commit()

            # 第二路: ChromaDB 语义检索（补充 SQLite 没命中的）
            if self._memory_collection is not None and len(results) < limit:
                try:
                    chroma_results = self._memory_collection.query(
                        query_texts=[context],
                        n_results=limit,
                    )
                    if chroma_results and chroma_results.get("ids"):
                        for i, doc_id in enumerate(chroma_results["ids"][0]):
                            if doc_id in seen_keys:
                                continue
                            doc_text = chroma_results["documents"][0][i] if chroma_results.get("documents") else ""
                            # 从 SQLite 查完整记录
                            with self._get_conn() as conn:
                                row = conn.execute(
                                    "SELECT * FROM memories WHERE key = ?", (doc_id,)
                                ).fetchone()
                                if row:
                                    mem = Memory(
                                        id=row["id"], mtype=row["mtype"], key=row["key"],
                                        value=row["value"], confidence=row["confidence"],
                                        source=row["source"],
                                        created_at=row["created_at"],
                                        last_accessed=row["last_accessed"],
                                        access_count=row["access_count"],
                                    )
                                    results.append(mem)
                                    seen_keys.add(doc_id)
                                    if len(results) >= limit:
                                        break
                except Exception:
                    pass

        return results[:limit]

    def list_all(self, mtype: str = "") -> List[Memory]:
        """列出所有记忆，可按类型过滤。"""
        with self._lock:
            with self._get_conn() as conn:
                if mtype:
                    rows = conn.execute(
                        "SELECT * FROM memories WHERE mtype = ? ORDER BY confidence DESC",
                        (mtype,)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM memories ORDER BY mtype, confidence DESC"
                    ).fetchall()

        return [Memory(
            id=r["id"], mtype=r["mtype"], key=r["key"], value=r["value"],
            confidence=r["confidence"], source=r["source"],
            created_at=r["created_at"], last_accessed=r["last_accessed"],
            access_count=r["access_count"],
        ) for r in rows]

    def forget(self, key: str) -> bool:
        """删除一条记忆（SQLite + ChromaDB）。"""
        with self._lock:
            with self._get_conn() as conn:
                cur = conn.execute("DELETE FROM memories WHERE key = ?", (key,))
                conn.commit()
                deleted = cur.rowcount > 0
            if deleted and self._memory_collection is not None:
                try:
                    self._memory_collection.delete(ids=[key])
                except Exception:
                    pass
            return deleted

    def decay(self, threshold: float = 0.1) -> int:
        """衰减低置信度记忆，删除置信度低于阈值的。返回删除数。"""
        with self._lock:
            with self._get_conn() as conn:
                cur = conn.execute(
                    "DELETE FROM memories WHERE confidence < ? AND mtype != 'correction'",
                    (threshold,)
                )
                conn.commit()
                return cur.rowcount


_store: Optional[MemoryStore] = None


def get_memory_store() -> MemoryStore:
    """获取全局 MemoryStore 单例。"""
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store
