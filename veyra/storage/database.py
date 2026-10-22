# veyra/storage/database.py
"""Connexion et schéma SQLite de VEYRA.

Base locale unique (aucun service externe) :
- ``settings`` : configuration clé/valeur ;
- ``events``   : historique structuré (jamais de données biométriques) ;
- ``profiles`` : profils utilisateurs avec empreinte chiffrée au repos.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    type TEXT NOT NULL,
    source TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    message TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);

CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    embedding_blob BLOB NOT NULL,
    kdf_params TEXT NOT NULL DEFAULT '{}'
);
"""


class Database:
    """Wrapper thread-safe d'une connexion SQLite (check_same_thread=False + verrou)."""

    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(_SCHEMA)
            self._conn.execute(
                "INSERT OR REPLACE INTO settings(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._conn.commit()
        logger.info("Base SQLite ouverte : %s", self._path)

    # ------------------------------------------------------------- settings

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            self._conn.commit()

    # --------------------------------------------------------------- events

    def add_event(self, ts: float, type_: str, source: str, message: str,
                  severity: str = "info", details_json: str = "{}") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO events(ts, type, source, severity, message, details) "
                "VALUES(?,?,?,?,?,?)",
                (ts, type_, source, severity, message, details_json),
            )
            self._conn.commit()

    def recent_events(self, limit: int = 200) -> list[dict[str, object]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, type, source, severity, message, details "
                "FROM events ORDER BY ts DESC LIMIT ?", (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def clear_events(self) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM events")
            self._conn.commit()
        return cur.rowcount

    # -------------------------------------------------------------- profiles

    def save_profile(self, user_key: str, display_name: str, embedding_blob: bytes,
                     kdf_params_json: str) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO profiles(user_key, display_name, created_at, updated_at, "
                "embedding_blob, kdf_params) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(user_key) DO UPDATE SET "
                "display_name=excluded.display_name, updated_at=excluded.updated_at, "
                "embedding_blob=excluded.embedding_blob, kdf_params=excluded.kdf_params",
                (user_key, display_name, now, now, embedding_blob, kdf_params_json),
            )
            self._conn.commit()

    def get_profile(self, user_key: str) -> dict[str, object] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT user_key, display_name, created_at, updated_at, embedding_blob, "
                "kdf_params FROM profiles WHERE user_key=?",
                (user_key,),
            ).fetchone()
        return dict(row) if row else None

    def list_profiles(self) -> list[dict[str, object]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT user_key, display_name, created_at, updated_at FROM profiles "
                "ORDER BY created_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_profile(self, user_key: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM profiles WHERE user_key=?", (user_key,))
            self._conn.commit()
        return cur.rowcount > 0

    def delete_all_profiles(self) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM profiles")
            self._conn.commit()
        return cur.rowcount

    # -------------------------------------------------------------- cycle

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.commit()
                self._conn.close()
            except sqlite3.Error:
                logger.exception("Erreur à la fermeture de la base.")
