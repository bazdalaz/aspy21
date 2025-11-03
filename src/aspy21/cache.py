from __future__ import annotations

import sqlite3
from pathlib import Path


class SmartCache:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value BLOB)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hist (
                  tag TEXT,
                  ts  TEXT,
                  value BLOB,
                  status INTEGER,
                  PRIMARY KEY (tag, ts)
                )
            """)

    def put_meta(self, key: str, value: bytes) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("REPLACE INTO meta (key, value) VALUES (?,?)", (key, value))

    def get_meta(self, key: str) -> bytes | None:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("SELECT value FROM meta WHERE key=?", (key,))
            row = cur.fetchone()
            return row[0] if row else None
