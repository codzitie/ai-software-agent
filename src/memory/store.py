"""Storage layer. Everything else talks to the Store interface only.

To move to MySQL or Firestore, write another class implementing Store
and return it from get_store(). Nothing else changes.
"""
import json
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from typing import Any

from config import settings


class Store(ABC):
    # ---- per-thread run context (short-term) ----
    @abstractmethod
    def append_record(self, thread_id: str, agent: str, stage: str, kind: str, payload: Any) -> None: ...

    @abstractmethod
    def list_records(
        self, thread_id: str, agent: str | None = None, kind: str | None = None, limit: int = 50
    ) -> list[dict]: ...

    @abstractmethod
    def put_summary(self, thread_id: str, text: str) -> None: ...

    @abstractmethod
    def get_summary(self, thread_id: str) -> str | None: ...

    # ---- per-project persistent memory (long-term) ----
    @abstractmethod
    def put_memory(self, project_id: str, kind: str, key: str, content: str) -> bool:
        """Upsert. Returns True if the content is new or changed."""

    @abstractmethod
    def get_memory(self, project_id: str, kind: str, key: str) -> str | None: ...

    @abstractmethod
    def list_memories(self, project_id: str, kind: str | None = None) -> list[dict]: ...

    @abstractmethod
    def delete_memory(self, project_id: str, kind: str, key: str) -> None: ...


class SQLiteStore(Store):
    def __init__(self, path):
        path = settings.Path(path) if hasattr(settings, "Path") else path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL, agent TEXT NOT NULL, stage TEXT NOT NULL,
                kind TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_records_thread ON records(thread_id, agent, kind);
            CREATE TABLE IF NOT EXISTS summaries (
                thread_id TEXT PRIMARY KEY, text TEXT NOT NULL, updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memories (
                project_id TEXT NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL,
                content TEXT NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY (project_id, kind, key)
            );
            """
        )

    def _run(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur.fetchall()

    # ---- records ----
    def append_record(self, thread_id, agent, stage, kind, payload):
        self._run(
            "INSERT INTO records(thread_id, agent, stage, kind, payload, created_at) VALUES (?,?,?,?,?,?)",
            (thread_id, agent, stage, kind, json.dumps(payload, default=str), time.time()),
        )

    def list_records(self, thread_id, agent=None, kind=None, limit=50):
        sql, params = "SELECT * FROM records WHERE thread_id=?", [thread_id]
        if agent:
            sql += " AND agent=?"
            params.append(agent)
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = self._run(sql, tuple(params))
        return [
            {**dict(r), "payload": json.loads(r["payload"])} for r in reversed(rows)  # oldest first
        ]

    # ---- summaries ----
    def put_summary(self, thread_id, text):
        self._run(
            "INSERT INTO summaries(thread_id, text, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(thread_id) DO UPDATE SET text=excluded.text, updated_at=excluded.updated_at",
            (thread_id, text, time.time()),
        )

    def get_summary(self, thread_id):
        rows = self._run("SELECT text FROM summaries WHERE thread_id=?", (thread_id,))
        return rows[0]["text"] if rows else None

    # ---- memories ----
    def put_memory(self, project_id, kind, key, content):
        if self.get_memory(project_id, kind, key) == content:
            return False
        self._run(
            "INSERT INTO memories(project_id, kind, key, content, updated_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(project_id, kind, key) DO UPDATE "
            "SET content=excluded.content, updated_at=excluded.updated_at",
            (project_id, kind, key, content, time.time()),
        )
        return True

    def get_memory(self, project_id, kind, key):
        rows = self._run(
            "SELECT content FROM memories WHERE project_id=? AND kind=? AND key=?",
            (project_id, kind, key),
        )
        return rows[0]["content"] if rows else None

    def list_memories(self, project_id, kind=None):
        sql, params = "SELECT kind, key, content, updated_at FROM memories WHERE project_id=?", [project_id]
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        sql += " ORDER BY updated_at"
        return [dict(r) for r in self._run(sql, tuple(params))]

    def delete_memory(self, project_id, kind, key):
        self._run(
            "DELETE FROM memories WHERE project_id=? AND kind=? AND key=?",
            (project_id, kind, key),
        )


_store: Store | None = None


def get_store() -> Store:
    """Process-wide singleton, chosen by settings.STORE_BACKEND."""
    global _store
    if _store is None:
        if settings.STORE_BACKEND == "sqlite":
            _store = SQLiteStore(settings.STORE_DB_PATH)
        else:
            raise NotImplementedError(f"Store backend '{settings.STORE_BACKEND}' is not built yet")
    return _store