from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from perennial.models import Task, Triage

MAX_ATTEMPTS = 3
OPEN = ("new", "ready", "needs_human")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY, source TEXT NOT NULL, ext_id TEXT NOT NULL, title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'new',
  decision TEXT, value INTEGER, effort INTEGER, reason TEXT,
  attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, workspace TEXT NOT NULL,
  started_at TEXT NOT NULL, ended_at TEXT, ok INTEGER, cost_usd REAL NOT NULL DEFAULT 0, summary TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ideas (
  id TEXT PRIMARY KEY, title TEXT NOT NULL UNIQUE, pitch TEXT NOT NULL, value INTEGER NOT NULL,
  effort INTEGER NOT NULL, novelty INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'new', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY, task_id TEXT NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def event(self, kind: str, **data) -> None:
        with self.db:
            self.db.execute("INSERT INTO events(ts,kind,data) VALUES(?,?,?)", (now(), kind, json.dumps(data)))

    def last_event_id(self) -> int:
        return self.db.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0]

    def events_after(self, after_id: int) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM events WHERE id>? ORDER BY id", (after_id,)).fetchall()]

    def sync(self, source: str, tasks: list[Task]) -> list[str]:
        """Insert unseen tasks; mark open tasks of this source that vanished as 'gone'. Returns new ids."""
        seen = {t.id for t in tasks}
        new_ids = []
        with self.db:
            for t in tasks:
                cur = self.db.execute(
                    "INSERT OR IGNORE INTO tasks(id,source,ext_id,title,body,url,created_at,updated_at)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (t.id, t.source, t.ext_id, t.title, t.body, t.url, now(), now()),
                )
                if cur.rowcount:
                    new_ids.append(t.id)
                else:  # a task that came back after vanishing is open again
                    self.db.execute("UPDATE tasks SET status='new', updated_at=? WHERE id=? AND status='gone'", (now(), t.id))
            q = f"SELECT id FROM tasks WHERE source=? AND status IN ({','.join('?' * len(OPEN))})"
            for (tid,) in self.db.execute(q, (source, *OPEN)).fetchall():
                if tid not in seen:
                    self.db.execute("UPDATE tasks SET status='gone', updated_at=? WHERE id=?", (now(), tid))
        return new_ids

    def tasks(self, status: str | None = None) -> list[dict]:
        if status:
            rows = self.db.execute("SELECT * FROM tasks WHERE status=? ORDER BY created_at, id", (status,))
        else:
            rows = self.db.execute("SELECT * FROM tasks ORDER BY created_at, id")
        return [dict(r) for r in rows.fetchall()]

    def get_task(self, tid: str) -> dict:
        return dict(self.db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone())

    def set_status(self, tid: str, status: str) -> None:
        with self.db:
            self.db.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", (status, now(), tid))

    def set_triage(self, tid: str, tr: Triage) -> None:
        status = {"do": "ready", "ask": "needs_human", "skip": "skipped"}[tr.decision]
        with self.db:
            self.db.execute(
                "UPDATE tasks SET status=?, decision=?, value=?, effort=?, reason=?, updated_at=? WHERE id=?",
                (status, tr.decision, tr.value, tr.effort, tr.reason, now(), tid),
            )

    def ready_tasks(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM tasks WHERE status='ready' AND attempts < ?"
            " ORDER BY CAST(value AS REAL)/MAX(effort,1) DESC, created_at",
            (MAX_ATTEMPTS,),
        )
        return [dict(r) for r in rows.fetchall()]

    def next_ready(self) -> dict | None:
        ready = self.ready_tasks()
        return ready[0] if ready else None

    def start_run(self, tid: str, workspace: str) -> int:
        with self.db:
            cur = self.db.execute(
                "INSERT INTO runs(task_id,workspace,started_at) VALUES(?,?,?)", (tid, workspace, now())
            )
            self.db.execute("UPDATE tasks SET status='running', updated_at=? WHERE id=?", (now(), tid))
            return int(cur.lastrowid)

    def finish_run(self, rid: int, ok: bool, cost_usd: float, summary: str) -> None:
        with self.db:
            self.db.execute(
                "UPDATE runs SET ended_at=?, ok=?, cost_usd=?, summary=? WHERE id=?",
                (now(), int(ok), cost_usd, summary, rid),
            )
            (tid,) = self.db.execute("SELECT task_id FROM runs WHERE id=?", (rid,)).fetchone()
            if ok:
                self.db.execute("UPDATE tasks SET status='done', updated_at=? WHERE id=?", (now(), tid))
            else:
                self.db.execute(
                    "UPDATE tasks SET attempts=attempts+1,"
                    " status=CASE WHEN attempts+1>=? THEN 'parked' ELSE 'ready' END, updated_at=? WHERE id=?",
                    (MAX_ATTEMPTS, now(), tid),
                )

    def spent_today(self) -> float:
        """Work runs plus triage and ideation calls (logged as events with a cost)."""
        day = now()[:10]
        (runs,) = self.db.execute(
            "SELECT COALESCE(SUM(cost_usd),0) FROM runs WHERE substr(started_at,1,10)=?", (day,)
        ).fetchone()
        (tri,) = self.db.execute(
            "SELECT COALESCE(SUM(json_extract(data,'$.cost')),0) FROM events WHERE kind IN ('triaged','ideated') AND substr(ts,1,10)=?",
            (day,),
        ).fetchone()
        return float(runs) + float(tri)

    def runs_since(self, iso: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT r.*, t.title, t.url FROM runs r JOIN tasks t ON t.id=r.task_id"
            " WHERE r.started_at>=? ORDER BY r.id",
            (iso,),
        )
        return [dict(r) for r in rows.fetchall()]

    def get(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, value: str) -> None:
        with self.db:
            self.db.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    # --- ideas -----------------------------------------------------------------------------
    def add_ideas(self, ideas: list[dict]) -> int:
        n = 0
        with self.db:
            for i in ideas:
                iid = hashlib.sha256(i["title"].encode()).hexdigest()[:12]
                cur = self.db.execute(
                    "INSERT OR IGNORE INTO ideas(id,title,pitch,value,effort,novelty,created_at) VALUES(?,?,?,?,?,?,?)",
                    (iid, i["title"], i["pitch"], i["value"], i["effort"], i["novelty"], now()),
                )
                n += cur.rowcount
        return n

    def ideas(self, status: str | None = None) -> list[dict]:
        q, args = ("SELECT * FROM ideas WHERE status=? ORDER BY created_at, id", (status,)) if status else (
            "SELECT * FROM ideas ORDER BY created_at, id", ())
        return [dict(r) for r in self.db.execute(q, args).fetchall()]

    def idea_titles(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT title FROM ideas").fetchall()]

    def queue_best_idea(self) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM ideas WHERE status='new'"
            " ORDER BY CAST(value*novelty AS REAL)/MAX(effort,1) DESC, created_at LIMIT 1"
        ).fetchone()
        if not row:
            return None
        with self.db:
            self.db.execute("UPDATE ideas SET status='queued' WHERE id=?", (row["id"],))
        return dict(row) | {"status": "queued"}

    # --- approvals -------------------------------------------------------------------------
    def add_approval(self, aid: str, task_id: str, action: str, payload: dict) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO approvals(id,task_id,action,payload,created_at) VALUES(?,?,?,?,?)",
                (aid, task_id, action, json.dumps(payload), now()),
            )

    def approvals(self, status: str | None = None) -> list[dict]:
        q, args = ("SELECT * FROM approvals WHERE status=? ORDER BY created_at, id", (status,)) if status else (
            "SELECT * FROM approvals ORDER BY created_at, id", ())
        return [dict(r) | {"payload": json.loads(r["payload"])} for r in self.db.execute(q, args).fetchall()]

    def set_approval(self, aid: str, status: str) -> None:
        with self.db:
            self.db.execute("UPDATE approvals SET status=? WHERE id=?", (status, aid))
