"""Shared task claims so several perennials never run the same task."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class Claims:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS claims (task_id TEXT PRIMARY KEY, owner TEXT NOT NULL, at TEXT NOT NULL)")

    def _db(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def claim(self, task_id: str, owner: str) -> bool:
        with self._db() as db:
            db.execute("INSERT OR IGNORE INTO claims(task_id,owner,at) VALUES(?,?,?)",
                       (task_id, owner, datetime.now(timezone.utc).isoformat(timespec="seconds")))
            row = db.execute("SELECT owner FROM claims WHERE task_id=?", (task_id,)).fetchone()
        return row is not None and row[0] == owner

    def release(self, task_id: str, owner: str) -> None:
        with self._db() as db:
            db.execute("DELETE FROM claims WHERE task_id=? AND owner=?", (task_id, owner))

    def owner_of(self, task_id: str) -> str | None:
        with self._db() as db:
            row = db.execute("SELECT owner FROM claims WHERE task_id=?", (task_id,)).fetchone()
        return row[0] if row else None
