# Perennial Phase 1 — Core Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One always-on perennial runs under launchd as a sandboxed macOS user. It reads Markdown and GitHub todos, triages them, does the `do` tasks alone in its own workspaces, opens PRs, and sends one daily digest. A kill switch and budget caps bound it.

**Architecture:** A Python supervisor ticks every 5 minutes. Source adapters return `Task`s, which are synced into SQLite. A cheap Claude call triages new tasks. The executor runs headless Claude Code (`claude -p`) in a per-task workspace, under per-run and per-day budget caps. All outbound traffic goes through a file outbox. A relay on the host side forwards only allowlisted message kinds to the existing `distress_call` CLI, so the sandbox never holds messaging credentials. See `docs/design.md`.

**Tech Stack:** Python 3.13 (uv), stdlib only (`sqlite3`, `tomllib`, `subprocess`, `json`, `hashlib`), pytest, the `claude` CLI, the `gh` CLI, launchd.

---

## File structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata, the `perennial` console script, pytest config |
| `src/perennial/models.py` | `Task`, `Triage`, `RunOutput` dataclasses; `task_id()` |
| `src/perennial/config.py` | Load and validate `config.toml` into `Config` |
| `src/perennial/store.py` | SQLite schema, sync of source tasks, run accounting, kv |
| `src/perennial/sources/markdown.py` | `- [ ]` checklist adapter |
| `src/perennial/sources/github.py` | Labelled GitHub issues adapter (via `gh`) |
| `src/perennial/sources/__init__.py` | `load_sources(config)` factory |
| `src/perennial/policy.py` | Kill switch, budget, autonomy levels |
| `src/perennial/runner.py` | `Runner` protocol + `ClaudeRunner` (subprocess) |
| `src/perennial/triage.py` | Prompt + parse a triage decision |
| `src/perennial/executor.py` | Workspace setup, run, PR for GitHub tasks |
| `src/perennial/gate.py` | Outbox writer (sandbox side) + relay (host side) |
| `src/perennial/supervisor.py` | `tick()` orchestration + digest |
| `src/perennial/cli.py` | `perennial tick / loop / status / stop / start / relay` |
| `deploy/setup-sandbox-user.sh` | Create the `perennial` user and the shared dirs; lock down the owner's home |
| `deploy/export-snapshots.sh` | Host side: copy allowlisted todo files into the shared inbox |
| `deploy/launchd/*.plist` | Supervisor (sandbox user), relay + snapshot jobs (owner) |
| `config.example.toml` | Documented example; the real config lives in `~/.perennial/` |
| `tests/…` | One test file per module |

---

### Task 1: Scaffold

**Files:**
- Create: `pyproject.toml`, `src/perennial/__init__.py`, `tests/__init__.py`, `.gitignore`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "perennial"
version = "0.1.0"
description = "Always-on local agents that work your todo lists"
requires-python = ">=3.13"
dependencies = []

[project.scripts]
perennial = "perennial.cli:main"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/perennial"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: Write `.gitignore` and empty package files**

```gitignore
.venv/
__pycache__/
*.sqlite
config.toml
.perennial/
```

`src/perennial/__init__.py`:
```python
__version__ = "0.1.0"
```

`tests/__init__.py`: empty file.

- [ ] **Step 3: Install and verify**

Run: `uv sync && uv run pytest -q`
Expected: `no tests ran`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml .gitignore src tests && git commit -m "chore: scaffold perennial package"
```

---

### Task 2: Models

**Files:**
- Create: `src/perennial/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
from perennial.models import Task, task_id


def test_task_id_is_stable_and_source_scoped():
    a = task_id("markdown:Today.md", "fix the invoice script")
    b = task_id("markdown:Today.md", "fix the invoice script")
    c = task_id("github:org/repo", "fix the invoice script")
    assert a == b
    assert a != c
    assert len(a) == 16


def test_task_builds_its_id():
    t = Task.new(source="github:org/repo", ext_id="12", title="Add CI", body="", url="https://x/12")
    assert t.id == task_id("github:org/repo", "12")
    assert t.kind == "github"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'perennial.models'`

- [ ] **Step 3: Implement**

```python
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


def task_id(source: str, ext_id: str) -> str:
    return hashlib.sha256(f"{source}\x00{ext_id}".encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Task:
    id: str
    source: str  # "<kind>:<location>", e.g. "markdown:Today.md", "github:org/repo"
    ext_id: str
    title: str
    body: str = ""
    url: str = ""

    @property
    def kind(self) -> str:
        return self.source.split(":", 1)[0]

    @classmethod
    def new(cls, source: str, ext_id: str, title: str, body: str = "", url: str = "") -> "Task":
        return cls(id=task_id(source, ext_id), source=source, ext_id=ext_id, title=title, body=body, url=url)


@dataclass(frozen=True)
class Triage:
    decision: str  # "do" | "ask" | "skip"
    value: int  # 1..5
    effort: int  # 1..5
    reason: str


@dataclass(frozen=True)
class RunOutput:
    ok: bool
    cost_usd: float
    summary: str
    raw: dict = field(default_factory=dict)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/perennial/models.py tests/test_models.py && git commit -m "feat: task, triage and run models"
```

---

### Task 3: Config

**Files:**
- Create: `src/perennial/config.py`, `config.example.toml`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from perennial.config import ConfigError, load_config

GOOD = """
[perennial]
name = "ember"
charter = "You maintain the owner's side projects."
autonomy = 2
daily_budget_usd = 20
run_budget_usd = 3
run_timeout_s = 3600
triage_model = "haiku"
work_model = "sonnet"
digest_hour = 18
home = "{home}"

[[sources]]
type = "markdown"
path = "{home}/inbox/Today.md"

[[sources]]
type = "github"
repos = ["perennial-bot/sandbox"]
label = "perennial"
"""


def test_load_good_config(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(GOOD.format(home=tmp_path))
    c = load_config(p)
    assert c.name == "ember"
    assert c.autonomy == 2
    assert c.store_path == tmp_path / "store.sqlite"
    assert c.workspaces == tmp_path / "workspaces"
    assert c.outbox == tmp_path / "outbox"
    assert c.stop_file == tmp_path / "STOP"
    assert [s["type"] for s in c.sources] == ["markdown", "github"]


def test_autonomy_above_two_is_rejected_in_phase_1(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(GOOD.format(home=tmp_path).replace("autonomy = 2", "autonomy = 3"))
    with pytest.raises(ConfigError, match="autonomy"):
        load_config(p)


def test_unknown_source_type_is_rejected(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(GOOD.format(home=tmp_path).replace('type = "github"', 'type = "gmail"'))
    with pytest.raises(ConfigError, match="gmail"):
        load_config(p)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL, `No module named 'perennial.config'`

- [ ] **Step 3: Implement**

```python
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

SOURCE_TYPES = {"markdown", "github"}
MAX_AUTONOMY_PHASE_1 = 2  # L3 (outside effects) needs the approval gate from phase 2


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    name: str
    charter: str
    autonomy: int
    daily_budget_usd: float
    run_budget_usd: float
    run_timeout_s: int
    triage_model: str
    work_model: str
    digest_hour: int
    home: Path
    sources: list[dict]

    @property
    def store_path(self) -> Path:
        return self.home / "store.sqlite"

    @property
    def workspaces(self) -> Path:
        return self.home / "workspaces"

    @property
    def outbox(self) -> Path:
        return self.home / "outbox"

    @property
    def stop_file(self) -> Path:
        return self.home / "STOP"


def load_config(path: Path) -> Config:
    data = tomllib.loads(Path(path).read_text())
    p = data.get("perennial") or {}
    try:
        cfg = Config(
            name=str(p["name"]),
            charter=str(p["charter"]),
            autonomy=int(p["autonomy"]),
            daily_budget_usd=float(p["daily_budget_usd"]),
            run_budget_usd=float(p["run_budget_usd"]),
            run_timeout_s=int(p["run_timeout_s"]),
            triage_model=str(p["triage_model"]),
            work_model=str(p["work_model"]),
            digest_hour=int(p["digest_hour"]),
            home=Path(p["home"]).expanduser(),
            sources=list(data.get("sources") or []),
        )
    except KeyError as e:
        raise ConfigError(f"missing [perennial] key: {e.args[0]}") from None
    if not 0 <= cfg.autonomy <= MAX_AUTONOMY_PHASE_1:
        raise ConfigError(f"autonomy must be 0..{MAX_AUTONOMY_PHASE_1} in phase 1, got {cfg.autonomy}")
    if cfg.run_budget_usd > cfg.daily_budget_usd:
        raise ConfigError("run_budget_usd cannot exceed daily_budget_usd")
    for s in cfg.sources:
        if s.get("type") not in SOURCE_TYPES:
            raise ConfigError(f"unknown source type: {s.get('type')}")
    return cfg
```

`config.example.toml`: the `GOOD` text from the test, with `home = "/Users/perennial/.perennial"`, the Markdown path `/Users/Shared/perennial/inbox/Today.md`, and a comment above each key explaining it.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_config.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/perennial/config.py config.example.toml tests/test_config.py && git commit -m "feat: config loading with phase-1 autonomy cap"
```

---

### Task 4: Store

**Files:**
- Create: `src/perennial/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

```python
from perennial.models import Task, Triage
from perennial.store import Store


def mk(title, src="markdown:Today.md"):
    return Task.new(source=src, ext_id=title, title=title)


def test_sync_inserts_new_and_marks_vanished_open_tasks_gone(tmp_path):
    s = Store(tmp_path / "s.sqlite")
    s.sync("markdown:Today.md", [mk("a"), mk("b")])
    assert {t["title"] for t in s.tasks(status="new")} == {"a", "b"}
    s.sync("markdown:Today.md", [mk("a")])
    assert {t["title"] for t in s.tasks(status="new")} == {"a"}
    assert {t["title"] for t in s.tasks(status="gone")} == {"b"}
    s.sync("markdown:Today.md", [mk("a"), mk("b")])
    assert {t["title"] for t in s.tasks(status="new")} == {"a", "b"}


def test_sync_does_not_touch_other_sources_or_done_tasks(tmp_path):
    s = Store(tmp_path / "s.sqlite")
    s.sync("markdown:Today.md", [mk("a")])
    s.sync("github:o/r", [mk("x", "github:o/r")])
    a = next(x for x in s.tasks(status="new") if x["title"] == "a")
    s.set_status(a["id"], "done")
    s.sync("markdown:Today.md", [])
    assert [t["title"] for t in s.tasks(status="done")] == ["a"]
    assert [t["title"] for t in s.tasks(status="new")] == ["x"]


def test_triage_and_pick_orders_by_value_over_effort(tmp_path):
    s = Store(tmp_path / "s.sqlite")
    s.sync("markdown:Today.md", [mk("low"), mk("high")])
    ids = {t["title"]: t["id"] for t in s.tasks(status="new")}
    s.set_triage(ids["low"], Triage("do", value=2, effort=4, reason=""))
    s.set_triage(ids["high"], Triage("do", value=5, effort=1, reason=""))
    assert s.next_ready()["title"] == "high"


def test_failed_runs_park_after_three_attempts(tmp_path):
    s = Store(tmp_path / "s.sqlite")
    s.sync("markdown:Today.md", [mk("a")])
    tid = s.tasks(status="new")[0]["id"]
    s.set_triage(tid, Triage("do", 3, 3, ""))
    for _ in range(3):
        rid = s.start_run(tid, workspace="/w")
        s.finish_run(rid, ok=False, cost_usd=0.5, summary="boom")
    assert s.tasks(status="parked")[0]["id"] == tid
    assert s.spent_today() == 1.5


def test_kv_roundtrip(tmp_path):
    s = Store(tmp_path / "s.sqlite")
    assert s.get("digest_date") is None
    s.put("digest_date", "2026-10-01")
    assert s.get("digest_date") == "2026-10-01"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL, `No module named 'perennial.store'`

- [ ] **Step 3: Implement**

```python
from __future__ import annotations

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

    def next_ready(self) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM tasks WHERE status='ready' AND attempts < ?"
            " ORDER BY CAST(value AS REAL)/MAX(effort,1) DESC, created_at LIMIT 1",
            (MAX_ATTEMPTS,),
        ).fetchone()
        return dict(row) if row else None

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
        day = now()[:10]
        (s,) = self.db.execute(
            "SELECT COALESCE(SUM(cost_usd),0) FROM runs WHERE substr(started_at,1,10)=?", (day,)
        ).fetchone()
        return float(s)

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
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_store.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/perennial/store.py tests/test_store.py && git commit -m "feat: sqlite store with sync, triage, runs and budget accounting"
```

---

### Task 5: Markdown source

**Files:**
- Create: `src/perennial/sources/__init__.py` (empty for now), `src/perennial/sources/markdown.py`
- Test: `tests/test_source_markdown.py`

- [ ] **Step 1: Write the failing test**

```python
from perennial.sources.markdown import MarkdownSource

DOC = """# 2026-10-01
### Plan
- [ ] **Send the invoice** · today
- [x] Already done
  - [ ] Nested sub-item
Some text - [ ] not a checklist
### Ideas
- [ ] Build a CLI for the blog
"""


def test_reads_open_checklist_items_with_heading_context(tmp_path):
    p = tmp_path / "Today.md"
    p.write_text(DOC)
    tasks = MarkdownSource(p).fetch()
    titles = [t.title for t in tasks]
    assert titles == ["Send the invoice · today", "Nested sub-item", "Build a CLI for the blog"]
    assert tasks[2].body == "Section: Ideas\nBuild a CLI for the blog"
    assert tasks[0].source == "markdown:Today.md"


def test_missing_file_yields_nothing(tmp_path):
    assert MarkdownSource(tmp_path / "nope.md").fetch() == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_source_markdown.py -v`
Expected: FAIL, `No module named 'perennial.sources'`

- [ ] **Step 3: Implement**

```python
from __future__ import annotations

import re
from pathlib import Path

from perennial.models import Task

ITEM = re.compile(r"^\s*- \[ \] (.+?)\s*$")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$")
EMPHASIS = re.compile(r"(\*\*|__|`)")


class MarkdownSource:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.source = f"markdown:{self.path.name}"

    def fetch(self) -> list[Task]:
        if not self.path.exists():
            return []
        section = ""
        out = []
        for line in self.path.read_text().splitlines():
            if h := HEADING.match(line):
                section = h.group(1)
                continue
            if m := ITEM.match(line):
                title = EMPHASIS.sub("", m.group(1)).strip()[:300]
                body = f"Section: {section}\n{title}" if section else title
                out.append(Task.new(source=self.source, ext_id=title, title=title, body=body))
        return out
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_source_markdown.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/perennial/sources tests/test_source_markdown.py && git commit -m "feat: markdown checklist source"
```

---

### Task 6: GitHub source

**Files:**
- Create: `src/perennial/sources/github.py`
- Test: `tests/test_source_github.py`

- [ ] **Step 1: Write the failing test**

```python
import json

import pytest

from perennial.sources.github import GitHubSource


def test_maps_gh_issue_json_to_tasks():
    calls = []

    def fake_gh(args):
        calls.append(args)
        return json.dumps([{"number": 7, "title": "Add CI", "body": "use uv", "url": "https://github.com/o/r/issues/7"}])

    src = GitHubSource(repo="o/r", label="perennial", gh=fake_gh)
    [t] = src.fetch()
    assert (t.source, t.ext_id, t.title, t.url) == ("github:o/r", "7", "Add CI", "https://github.com/o/r/issues/7")
    assert t.body == "use uv"
    assert calls == [["issue", "list", "--repo", "o/r", "--label", "perennial", "--state", "open",
                      "--limit", "50", "--json", "number,title,body,url"]]


def test_gh_failure_raises_so_supervisor_skips_sync():
    # If fetch returned [] on error, Store.sync would mark every open task of the repo 'gone'.
    def broken(args):
        raise RuntimeError("gh exploded")

    with pytest.raises(RuntimeError):
        GitHubSource(repo="o/r", label="x", gh=broken).fetch()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_source_github.py -v`
Expected: FAIL, `No module named 'perennial.sources.github'`

- [ ] **Step 3: Implement**

```python
from __future__ import annotations

import json
import subprocess
from collections.abc import Callable

from perennial.models import Task


def run_gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, timeout=60).stdout


class GitHubSource:
    def __init__(self, repo: str, label: str, gh: Callable[[list[str]], str] = run_gh):
        self.repo, self.label, self.gh = repo, label, gh
        self.source = f"github:{repo}"

    def fetch(self) -> list[Task]:
        """Raises on gh failure. The supervisor catches it and skips the sync for this source."""
        raw = self.gh(["issue", "list", "--repo", self.repo, "--label", self.label, "--state", "open",
                       "--limit", "50", "--json", "number,title,body,url"])
        return [
            Task.new(source=self.source, ext_id=str(i["number"]), title=i["title"], body=i.get("body") or "", url=i["url"])
            for i in json.loads(raw)
        ]
```

- [ ] **Step 4: Add the factory in `src/perennial/sources/__init__.py`**

```python
from __future__ import annotations

from pathlib import Path

from perennial.sources.github import GitHubSource
from perennial.sources.markdown import MarkdownSource


def load_sources(cfg) -> list:
    out = []
    for s in cfg.sources:
        if s["type"] == "markdown":
            out.append(MarkdownSource(Path(s["path"])))
        elif s["type"] == "github":
            out.extend(GitHubSource(repo=r, label=s.get("label", "perennial")) for r in s["repos"])
    return out
```

- [ ] **Step 5: Run tests and commit**

Run: `uv run pytest tests/test_source_github.py -v`
Expected: 2 passed

```bash
git add src/perennial/sources tests/test_source_github.py && git commit -m "feat: github issues source + source factory"
```

---

### Task 7: Policy

**Files:**
- Create: `src/perennial/policy.py`
- Test: `tests/test_policy.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from perennial.policy import LEVELS, Blocked, Policy


class FakeStore:
    def __init__(self, spent):
        self._spent = spent

    def spent_today(self):
        return self._spent


def test_kill_switch(tmp_path):
    p = Policy(stop_file=tmp_path / "STOP", autonomy=2, daily_budget=10, run_budget=2)
    assert not p.stopped()
    (tmp_path / "STOP").write_text("")
    assert p.stopped()


def test_budget_needs_room_for_a_full_run(tmp_path):
    p = Policy(stop_file=tmp_path / "STOP", autonomy=2, daily_budget=10, run_budget=2)
    assert p.can_spend(FakeStore(7.9))
    assert not p.can_spend(FakeStore(8.1))


@pytest.mark.parametrize("action,allowed", [
    ("read", True), ("build", True), ("push_own", True), ("open_pr", True),
    ("notify_owner", True), ("message_human", False), ("publish", False), ("merge_main", False),
    ("send_as_owner", False), ("spend_money", False),
])
def test_autonomy_two_allows_build_and_pr_but_not_outside_effects(tmp_path, action, allowed):
    p = Policy(stop_file=tmp_path / "STOP", autonomy=2, daily_budget=10, run_budget=2)
    if allowed:
        p.require(action)
    else:
        with pytest.raises(Blocked):
            p.require(action)


def test_level_four_actions_are_never_allowed():
    assert LEVELS["send_as_owner"] == 4 and LEVELS["spend_money"] == 4
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_policy.py -v`
Expected: FAIL, `No module named 'perennial.policy'`

- [ ] **Step 3: Implement**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# L0 read · L1 build in sandbox · L2 ship to own space · L3 outside effects · L4 never
LEVELS = {
    "read": 0,
    "build": 1,
    "notify_owner": 1,
    "push_own": 2,
    "open_pr": 2,
    "message_human": 3,
    "publish": 3,
    "merge_main": 3,
    "write_external": 3,
    "signup": 3,
    "send_as_owner": 4,
    "spend_money": 4,
    "use_owner_credentials": 4,
}


class Blocked(PermissionError):
    pass


@dataclass(frozen=True)
class Policy:
    stop_file: Path
    autonomy: int
    daily_budget: float
    run_budget: float

    def stopped(self) -> bool:
        return Path(self.stop_file).exists()

    def can_spend(self, store) -> bool:
        return store.spent_today() + self.run_budget <= self.daily_budget

    def require(self, action: str) -> None:
        level = LEVELS[action]
        if level >= 4 or level > self.autonomy:
            raise Blocked(f"{action} (L{level}) not allowed at autonomy L{self.autonomy}")
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_policy.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add src/perennial/policy.py tests/test_policy.py && git commit -m "feat: policy with kill switch, budget and autonomy levels"
```

---

### Task 8: Claude runner

**Files:**
- Create: `src/perennial/runner.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: Write the failing test**

```python
import json
import subprocess

from perennial.runner import ClaudeRunner


def test_builds_headless_command_and_parses_json(tmp_path, monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        out = {"result": "did it", "total_cost_usd": 0.42, "is_error": False, "session_id": "s1"}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(out), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    r = ClaudeRunner(binary="claude").run("fix it", cwd=tmp_path, model="sonnet", budget_usd=3, timeout_s=60, system="be good")
    assert r.ok and r.cost_usd == 0.42 and r.summary == "did it"
    cmd = seen["cmd"]
    assert cmd[:3] == ["claude", "-p", "fix it"]
    for flag in ["--output-format", "json", "--model", "sonnet", "--max-budget-usd", "3",
                 "--permission-mode", "bypassPermissions", "--append-system-prompt", "be good"]:
        assert flag in cmd
    assert seen["kw"]["cwd"] == tmp_path and seen["kw"]["timeout"] == 60


def test_timeout_and_garbage_become_failed_runs(tmp_path, monkeypatch):
    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(subprocess, "run", boom)
    r = ClaudeRunner().run("x", cwd=tmp_path, model="m", budget_usd=1, timeout_s=1, system="")
    assert not r.ok and "timeout" in r.summary

    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="not json", stderr="err"))
    r = ClaudeRunner().run("x", cwd=tmp_path, model="m", budget_usd=1, timeout_s=1, system="")
    assert not r.ok and r.cost_usd == 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_runner.py -v`
Expected: FAIL, `No module named 'perennial.runner'`

- [ ] **Step 3: Implement**

```python
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Protocol

from perennial.models import RunOutput


class Runner(Protocol):
    def run(self, prompt: str, cwd: Path, model: str, budget_usd: float, timeout_s: int, system: str) -> RunOutput: ...


class ClaudeRunner:
    """Headless Claude Code. Runs inside the sandbox user, so bypassPermissions is bounded by the OS user."""

    def __init__(self, binary: str = "claude"):
        self.binary = binary

    def run(self, prompt, cwd, model, budget_usd, timeout_s, system) -> RunOutput:
        cmd = [self.binary, "-p", prompt, "--output-format", "json", "--model", model,
               "--max-budget-usd", f"{budget_usd:g}", "--permission-mode", "bypassPermissions",
               "--append-system-prompt", system]
        try:
            proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return RunOutput(ok=False, cost_usd=0.0, summary=f"timeout after {timeout_s}s")
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return RunOutput(ok=False, cost_usd=0.0, summary=(proc.stderr or proc.stdout)[-2000:])
        ok = proc.returncode == 0 and not data.get("is_error", False)
        return RunOutput(ok=ok, cost_usd=float(data.get("total_cost_usd") or 0), summary=str(data.get("result", ""))[-4000:], raw=data)
```

A run that times out reports cost 0, but it did spend money. The per-run `--max-budget-usd` cap still bounds the real spend. The digest flags timeouts so the owner sees them.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_runner.py -v`
Expected: 2 passed

- [ ] **Step 5: Verify the real JSON shape once, by hand**

Run: `cd /tmp && claude -p "say ok" --output-format json --model haiku --max-budget-usd 0.05 | python3 -c 'import json,sys; d=json.load(sys.stdin); print(sorted(d))'`
Expected: the keys include `result`, `total_cost_usd`, `is_error` (verified 1 Oct 2026 on Claude Code 2.1.281). An API error still exits with valid JSON: `subtype: "success"` but `is_error: true` and `result: "Credit balance is too low"`. The runner treats it as a failed run. Warnings go to stderr, so parsing stdout is safe.

**Auth gotcha:** if `ANTHROPIC_API_KEY` is set, it overrides the claude.ai subscription login. If that key has no credit, every run fails with "Credit balance is too low". The `perennial` user must NOT inherit that variable. It logs in with `claude` once, or gets its own funded key.

- [ ] **Step 6: Commit**

```bash
git add src/perennial/runner.py tests/test_runner.py && git commit -m "feat: headless claude runner"
```

---

### Task 9: Triage

**Files:**
- Create: `src/perennial/triage.py`
- Test: `tests/test_triage.py`

- [ ] **Step 1: Write the failing test**

```python
from perennial.models import RunOutput, Task
from perennial.triage import parse_triage, triage_prompt, triage


def test_prompt_contains_task_and_rules():
    t = Task.new(source="markdown:Today.md", ext_id="x", title="Book flights", body="Section: Plan\nBook flights")
    p = triage_prompt(t, charter="You build software.")
    assert "Book flights" in p and '"decision"' in p and "spend money" in p


def test_parse_accepts_json_inside_prose():
    tr = parse_triage('Sure. {"decision":"do","value":4,"effort":2,"reason":"small script"} done')
    assert (tr.decision, tr.value, tr.effort) == ("do", 4, 2)


def test_parse_failure_defaults_to_ask():
    tr = parse_triage("I am not sure")
    assert tr.decision == "ask"


def test_out_of_range_scores_are_clamped():
    tr = parse_triage('{"decision":"do","value":9,"effort":0,"reason":""}')
    assert (tr.value, tr.effort) == (5, 1)


class FakeRunner:
    def __init__(self, text):
        self.text = text

    def run(self, prompt, cwd, model, budget_usd, timeout_s, system):
        return RunOutput(ok=True, cost_usd=0.01, summary=self.text)


def test_triage_uses_cheap_budget(tmp_path):
    t = Task.new(source="s:x", ext_id="1", title="t")
    tr, cost = triage(t, FakeRunner('{"decision":"skip","value":1,"effort":1,"reason":"personal errand"}'),
                      cwd=tmp_path, model="haiku", charter="c")
    assert tr.decision == "skip" and cost == 0.01
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_triage.py -v`
Expected: FAIL, `No module named 'perennial.triage'`

- [ ] **Step 3: Implement**

```python
from __future__ import annotations

import json
import re
from pathlib import Path

from perennial.models import Task, Triage

TRIAGE_BUDGET_USD = 0.10
JSON_OBJ = re.compile(r"\{.*?\}", re.S)

RULES = """Decide if you can finish this task ALONE inside your own sandbox computer.
- "do": you can finish it with code, research, writing or prototypes on your own machine and repos.
- "ask": it needs the owner. It needs a human decision, a message to a person, the owner's accounts,
  publishing, signing up for services, or anything you cannot undo.
- "skip": it is a personal errand or physical task (post office, calls, travel), or not actionable.
You may never: spend money, send email or messages as the owner, use the owner's credentials, or delete outside your sandbox.
Answer ONLY with JSON: {"decision":"do|ask|skip","value":1-5,"effort":1-5,"reason":"one sentence"}"""


def triage_prompt(task: Task, charter: str) -> str:
    return f"{charter}\n\n{RULES}\n\nTask source: {task.source}\nTitle: {task.title}\nContext:\n{task.body[:2000]}"


def _clamp(v, lo=1, hi=5) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return 3


def parse_triage(text: str) -> Triage:
    for m in JSON_OBJ.finditer(text or ""):
        try:
            d = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if d.get("decision") in ("do", "ask", "skip"):
            return Triage(d["decision"], _clamp(d.get("value")), _clamp(d.get("effort")), str(d.get("reason", ""))[:300])
    return Triage("ask", 1, 5, "could not parse triage output")


def triage(task: Task, runner, cwd: Path, model: str, charter: str) -> tuple[Triage, float]:
    out = runner.run(triage_prompt(task, charter), cwd=cwd, model=model, budget_usd=TRIAGE_BUDGET_USD,
                     timeout_s=180, system="You are a careful triage step. Output JSON only.")
    return parse_triage(out.summary if out.ok else ""), out.cost_usd
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_triage.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/perennial/triage.py tests/test_triage.py && git commit -m "feat: triage prompt and robust parser"
```

---

### Task 10: Gate (outbox and relay)

**Files:**
- Create: `src/perennial/gate.py`
- Test: `tests/test_gate.py`

- [ ] **Step 1: Write the failing test**

```python
import json

import pytest

from perennial.gate import ALLOWED_KINDS, Outbox, relay_once
from perennial.policy import Blocked, Policy


def pol(tmp_path, autonomy=2):
    return Policy(stop_file=tmp_path / "STOP", autonomy=autonomy, daily_budget=10, run_budget=1)


def test_notify_writes_one_json_file(tmp_path):
    ob = Outbox(tmp_path / "outbox", pol(tmp_path))
    ob.notify("digest text", label="perennial-digest")
    [f] = list((tmp_path / "outbox").glob("*.json"))
    assert json.loads(f.read_text()) == {"kind": "notify", "label": "perennial-digest", "message": "digest text"}


def test_notify_blocked_at_autonomy_zero(tmp_path):
    with pytest.raises(Blocked):
        Outbox(tmp_path / "outbox", pol(tmp_path, autonomy=0)).notify("x", label="l")


def test_relay_sends_allowlisted_and_quarantines_the_rest(tmp_path):
    box = tmp_path / "outbox"
    box.mkdir()
    (box / "1.json").write_text(json.dumps({"kind": "notify", "label": "perennial-digest", "message": "hi"}))
    (box / "2.json").write_text(json.dumps({"kind": "email", "to": "x@y.z", "message": "hi"}))
    (box / "3.json").write_text("not json")
    sent = []
    n = relay_once(box, send=lambda msg, label: sent.append((msg, label)))
    assert n == 1 and sent == [("hi", "perennial-digest")]
    assert sorted(p.name for p in (box / "sent").iterdir()) == ["1.json"]
    assert sorted(p.name for p in (box / "rejected").iterdir()) == ["2.json", "3.json"]
    assert ALLOWED_KINDS == {"notify"}


def test_relay_truncates_long_messages(tmp_path):
    box = tmp_path / "outbox"
    box.mkdir()
    (box / "1.json").write_text(json.dumps({"kind": "notify", "label": "l", "message": "x" * 10000}))
    sent = []
    relay_once(box, send=lambda m, l: sent.append(m))
    assert len(sent[0]) == 3500
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_gate.py -v`
Expected: FAIL, `No module named 'perennial.gate'`

- [ ] **Step 3: Implement**

```python
"""The only path out of the sandbox.

Sandbox side: Outbox writes JSON requests into a directory the owner's user can read.
Host side: relay_once() runs as the owner. It forwards ONLY allowlisted kinds to the owner's
existing notifier (distress_call CLI), so the sandbox never holds messaging credentials.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path

ALLOWED_KINDS = {"notify"}  # phase 2 adds "approve"
MAX_LEN = 3500


class Outbox:
    def __init__(self, path: Path, policy):
        self.path, self.policy = Path(path), policy

    def notify(self, message: str, label: str) -> Path:
        self.policy.require("notify_owner")
        self.path.mkdir(parents=True, exist_ok=True)
        f = self.path / f"{int(time.time())}-{uuid.uuid4().hex[:8]}.json"
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps({"kind": "notify", "label": label, "message": message}))
        tmp.rename(f)  # atomic: the relay never reads a half-written file
        return f


def distress_send(cli: Path) -> Callable[[str, str], None]:
    def send(message: str, label: str) -> None:
        subprocess.run(["python3", str(cli), message, "--label", label], check=True, timeout=60)
    return send


def relay_once(outbox: Path, send: Callable[[str, str], None]) -> int:
    outbox = Path(outbox)
    (outbox / "sent").mkdir(exist_ok=True)
    (outbox / "rejected").mkdir(exist_ok=True)
    n = 0
    for f in sorted(outbox.glob("*.json")):
        try:
            req = json.loads(f.read_text())
            ok = isinstance(req, dict) and req.get("kind") in ALLOWED_KINDS and isinstance(req.get("message"), str)
        except json.JSONDecodeError:
            ok = False
        if not ok:
            shutil.move(f, outbox / "rejected" / f.name)
            continue
        send(req["message"][:MAX_LEN], str(req.get("label", "perennial"))[:40])
        shutil.move(f, outbox / "sent" / f.name)
        n += 1
    return n
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_gate.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/perennial/gate.py tests/test_gate.py && git commit -m "feat: outbox gate with allowlisted host relay"
```

---

### Task 11: Executor

**Files:**
- Create: `src/perennial/executor.py`
- Test: `tests/test_executor.py`

- [ ] **Step 1: Write the failing test**

```python
import subprocess

from perennial.executor import Executor, work_prompt
from perennial.models import RunOutput
from perennial.policy import Policy


class FakeRunner:
    def __init__(self, ok=True, touch=None):
        self.ok, self.touch, self.calls = ok, touch, []

    def run(self, prompt, cwd, model, budget_usd, timeout_s, system):
        self.calls.append((prompt, cwd, model, budget_usd))
        if self.touch:
            (cwd / self.touch).write_text("change")
        return RunOutput(ok=self.ok, cost_usd=1.25, summary="summary")


def pol(tmp_path):
    return Policy(stop_file=tmp_path / "STOP", autonomy=2, daily_budget=10, run_budget=2)


def task(kind="markdown", url=""):
    src = "markdown:Today.md" if kind == "markdown" else "github:o/r"
    return {"id": "abc123", "source": src, "ext_id": "7", "title": "Do thing", "body": "ctx", "url": url}


def test_markdown_task_runs_in_fresh_workspace(tmp_path):
    r = FakeRunner()
    ex = Executor(runner=r, policy=pol(tmp_path), workspaces=tmp_path / "ws", model="sonnet",
                  run_budget=2, timeout_s=60, charter="c", git=lambda *a, **k: None, gh=lambda *a: "")
    out, ws = ex.execute(task())
    assert out.ok and ws == tmp_path / "ws" / "abc123"
    assert r.calls[0][1] == ws and r.calls[0][3] == 2


def test_github_task_clones_branches_and_opens_pr_when_changed(tmp_path):
    git_calls, gh_calls = [], []

    def git(*args, cwd=None):
        git_calls.append(args)
        if args[:2] == ("status", "--porcelain"):
            return " M file\n"
        return ""

    def gh(*args):
        gh_calls.append(args)
        if args[:2] == ("repo", "clone"):
            (tmp_path / "ws" / "abc123").mkdir(parents=True, exist_ok=True)
        return "https://github.com/o/r/pull/9\n"

    ex = Executor(runner=FakeRunner(), policy=pol(tmp_path), workspaces=tmp_path / "ws", model="sonnet",
                  run_budget=2, timeout_s=60, charter="c", git=git, gh=gh)
    out, ws = ex.execute(task("github", url="https://github.com/o/r/issues/7"))
    assert gh_calls[0][:3] == ("repo", "clone", "o/r")
    assert ("checkout", "-b", "perennial/abc123") in git_calls
    assert any(c[:2] == ("pr", "create") for c in gh_calls)
    assert "pull/9" in out.summary


def test_prompt_demands_result_file():
    assert "RESULT.md" in work_prompt(task())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_executor.py -v`
Expected: FAIL, `No module named 'perennial.executor'`

- [ ] **Step 3: Implement**

```python
from __future__ import annotations

import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

from perennial.models import RunOutput


def run_git(*args, cwd=None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=300).stdout


def run_gh(*args) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, timeout=300).stdout


def work_prompt(task: dict) -> str:
    return (
        f"Task: {task['title']}\nSource: {task['source']} {task.get('url', '')}\nContext:\n{task['body'][:4000]}\n\n"
        "Work only inside the current directory. Finish the task end to end. Write tests where code is involved and run them.\n"
        "When done, write RESULT.md: what you did, how you verified it, and what is left. Keep it under 300 words.\n"
        "Do not create accounts, send messages, publish, or spend money. If the task needs that, stop and say so in RESULT.md."
    )


class Executor:
    def __init__(self, runner, policy, workspaces: Path, model: str, run_budget: float, timeout_s: int,
                 charter: str, git=run_git, gh=run_gh):
        self.runner, self.policy, self.workspaces = runner, policy, Path(workspaces)
        self.model, self.run_budget, self.timeout_s, self.charter = model, run_budget, timeout_s, charter
        self.git, self.gh = git, gh

    def execute(self, task: dict) -> tuple[RunOutput, Path]:
        self.policy.require("build")
        ws = self.workspaces / task["id"]
        if ws.exists():
            shutil.rmtree(ws)
        is_gh = task["source"].startswith("github:")
        if is_gh:
            repo = task["source"].split(":", 1)[1]
            self.workspaces.mkdir(parents=True, exist_ok=True)
            self.gh("repo", "clone", repo, str(ws))
            self.git("checkout", "-b", f"perennial/{task['id']}", cwd=ws)
        else:
            ws.mkdir(parents=True)
        out = self.runner.run(work_prompt(task), cwd=ws, model=self.model, budget_usd=self.run_budget,
                              timeout_s=self.timeout_s, system=self.charter)
        if out.ok and is_gh:
            out = self._ship(task, ws, out)
        return out, ws

    def _ship(self, task: dict, ws: Path, out: RunOutput) -> RunOutput:
        if not self.git("status", "--porcelain", cwd=ws).strip():
            return replace(out, summary=out.summary + "\n(no changes to ship)")
        self.policy.require("push_own")
        self.git("add", "-A", cwd=ws)
        self.git("commit", "-m", f"perennial: {task['title'][:60]}", cwd=ws)
        self.git("push", "-u", "origin", f"perennial/{task['id']}", cwd=ws)
        self.policy.require("open_pr")
        result = (ws / "RESULT.md").read_text()[:3000] if (ws / "RESULT.md").exists() else out.summary[:3000]
        url = self.gh("pr", "create", "--repo", task["source"].split(":", 1)[1], "--head", f"perennial/{task['id']}",
                      "--title", f"perennial: {task['title'][:60]}", "--body", f"Closes {task.get('url', '')}\n\n{result}").strip()
        return replace(out, summary=f"{out.summary}\nPR: {url}")
```

The test `gh` fake creates the workspace on `repo clone`, so `git status` runs in an existing dir. `RESULT.md` does not exist in the GitHub test, so the PR body falls back to the summary.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_executor.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/perennial/executor.py tests/test_executor.py && git commit -m "feat: executor with per-task workspace and PR shipping"
```

---

### Task 12: Supervisor tick and digest

**Files:**
- Create: `src/perennial/supervisor.py`
- Test: `tests/test_supervisor.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime

from perennial.models import RunOutput, Task, Triage
from perennial.policy import Policy
from perennial.store import Store
from perennial.supervisor import Supervisor


class Src:
    def __init__(self, tasks, source="markdown:Today.md", boom=False):
        self.tasks, self.source, self.boom = tasks, source, boom

    def fetch(self):
        if self.boom:
            raise RuntimeError("down")
        return self.tasks


class Ex:
    def __init__(self):
        self.ran = []

    def execute(self, task):
        self.ran.append(task["title"])
        return RunOutput(ok=True, cost_usd=1.0, summary="done"), f"/ws/{task['id']}"


class Outbox:
    def __init__(self):
        self.sent = []

    def notify(self, message, label):
        self.sent.append((label, message))


def make(tmp_path, sources, triage_fn, hour=18, daily=5):
    pol = Policy(stop_file=tmp_path / "STOP", autonomy=2, daily_budget=daily, run_budget=2)
    return Supervisor(store=Store(tmp_path / "s.sqlite"), sources=sources, policy=pol, executor=Ex(),
                      outbox=Outbox(), triage_fn=triage_fn, digest_hour=hour, name="ember")


def t(title):
    return Task.new(source="markdown:Today.md", ext_id=title, title=title)


def test_tick_triages_new_tasks_and_runs_one_ready(tmp_path):
    decisions = {"code it": Triage("do", 5, 1, ""), "call mom": Triage("skip", 1, 1, "")}
    sv = make(tmp_path, [Src([t("code it"), t("call mom")])], lambda task: (decisions[task.title], 0.01))
    sv.tick(now=datetime(2026, 10, 1, 9))
    assert sv.executor.ran == ["code it"]
    assert [x["title"] for x in sv.store.tasks(status="done")] == ["code it"]
    assert [x["title"] for x in sv.store.tasks(status="skipped")] == ["call mom"]


def test_stop_file_halts_everything(tmp_path):
    sv = make(tmp_path, [Src([t("a")])], lambda task: (Triage("do", 5, 1, ""), 0))
    (tmp_path / "STOP").write_text("")
    sv.tick(now=datetime(2026, 10, 1, 9))
    assert sv.store.tasks() == [] and sv.executor.ran == []


def test_failing_source_is_not_synced(tmp_path):
    sv = make(tmp_path, [Src([t("a")])], lambda task: (Triage("ask", 1, 1, ""), 0))
    sv.tick(now=datetime(2026, 10, 1, 9))
    sv.sources = [Src([], boom=True)]
    sv.tick(now=datetime(2026, 10, 1, 9, 5))
    assert [x["title"] for x in sv.store.tasks(status="needs_human")] == ["a"]


def test_budget_exhaustion_stops_execution(tmp_path):
    # daily $4, run headroom $2, each fake run costs $1: runs start at spent 0, 1, 2; at spent 3, 3+2 > 4.
    sv = make(tmp_path, [Src([t("a"), t("b"), t("c"), t("d")])], lambda task: (Triage("do", 3, 3, ""), 0), daily=4)
    for minute in range(6):
        sv.tick(now=datetime(2026, 10, 1, 9, minute))
    assert len(sv.executor.ran) == 3
    assert len(sv.store.tasks(status="ready")) == 1


def test_one_digest_per_day_after_digest_hour(tmp_path):
    sv = make(tmp_path, [Src([t("write docs")])], lambda task: (Triage("do", 3, 3, ""), 0))
    sv.tick(now=datetime(2026, 10, 1, 17))
    assert sv.outbox.sent == []
    sv.tick(now=datetime(2026, 10, 1, 18, 1))
    sv.tick(now=datetime(2026, 10, 1, 19))
    assert len(sv.outbox.sent) == 1
    label, msg = sv.outbox.sent[0]
    assert label == "perennial-digest" and "ember" in msg and "write docs" in msg
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_supervisor.py -v`
Expected: FAIL, `No module named 'perennial.supervisor'`

- [ ] **Step 3: Implement**

```python
from __future__ import annotations

from datetime import datetime

from perennial.models import Task


class Supervisor:
    def __init__(self, store, sources, policy, executor, outbox, triage_fn, digest_hour: int, name: str):
        self.store, self.sources, self.policy = store, sources, policy
        self.executor, self.outbox, self.triage_fn = executor, outbox, triage_fn
        self.digest_hour, self.name = digest_hour, name

    def tick(self, now: datetime | None = None) -> None:
        now = now or datetime.now()
        if self.policy.stopped():
            self.store.event("stopped")
            return
        self._refresh()
        self._triage_new()
        self._run_one()
        self._maybe_digest(now)

    def _refresh(self) -> None:
        for src in self.sources:
            try:
                tasks = src.fetch()
            except Exception as e:  # a failing source must not mark its tasks as gone
                self.store.event("source_error", source=getattr(src, "source", "?"), error=str(e)[:500])
                continue
            self.store.sync(src.source, tasks)

    def _triage_new(self) -> None:
        for row in self.store.tasks(status="new"):
            if self.policy.stopped() or not self.policy.can_spend(self.store):
                return
            task = Task(id=row["id"], source=row["source"], ext_id=row["ext_id"], title=row["title"],
                        body=row["body"], url=row["url"])
            tr, cost = self.triage_fn(task)
            self.store.set_triage(row["id"], tr)
            self.store.event("triaged", task=row["id"], decision=tr.decision, cost=cost)

    def _run_one(self) -> None:
        if self.policy.stopped() or not self.policy.can_spend(self.store):
            return
        task = self.store.next_ready()
        if not task:
            return
        rid = self.store.start_run(task["id"], workspace="")
        try:
            out, ws = self.executor.execute(task)
            self.store.finish_run(rid, ok=out.ok, cost_usd=out.cost_usd, summary=f"{out.summary}\nworkspace: {ws}")
        except Exception as e:
            self.store.finish_run(rid, ok=False, cost_usd=0.0, summary=f"executor error: {e}"[:2000])

    def _maybe_digest(self, now: datetime) -> None:
        day = now.date().isoformat()
        if now.hour < self.digest_hour or self.store.get("digest_date") == day:
            return
        runs = self.store.runs_since(day)
        lines = [f"{self.name} — {day}: {len(runs)} runs, ${sum(r['cost_usd'] for r in runs):.2f}"]
        for r in runs:
            mark = "done" if r["ok"] else "failed"
            lines.append(f"- {mark}: {r['title'][:80]} — {(r['summary'] or '').splitlines()[0][:120] if r['summary'] else ''}")
        asks = self.store.tasks(status="needs_human")
        if asks:
            lines.append(f"Needs you ({len(asks)}): " + "; ".join(a["title"][:60] for a in asks[:5]))
        parked = self.store.tasks(status="parked")
        if parked:
            lines.append(f"Parked after 3 failures: " + "; ".join(p["title"][:60] for p in parked[:5]))
        self.outbox.notify("\n".join(lines), label="perennial-digest")
        self.store.put("digest_date", day)
```

`runs_since(day)` compares ISO timestamps in UTC with a local date string. That is a small boundary error at midnight. Accept it in phase 1; the digest is a summary, not an accounting record.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_supervisor.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/perennial/supervisor.py tests/test_supervisor.py && git commit -m "feat: supervisor tick with stop, triage, run and daily digest"
```

---

### Task 13: CLI

**Files:**
- Create: `src/perennial/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
from perennial.cli import main


def test_stop_and_start_toggle_kill_switch(tmp_path, capsys):
    cfg = tmp_path / "config.toml"
    cfg.write_text(f"""
[perennial]
name = "ember"
charter = "c"
autonomy = 2
daily_budget_usd = 5
run_budget_usd = 1
run_timeout_s = 60
triage_model = "haiku"
work_model = "sonnet"
digest_hour = 18
home = "{tmp_path}"
""")
    assert main(["--config", str(cfg), "stop"]) == 0
    assert (tmp_path / "STOP").exists()
    assert main(["--config", str(cfg), "status"]) == 0
    assert "STOPPED" in capsys.readouterr().out
    assert main(["--config", str(cfg), "start"]) == 0
    assert not (tmp_path / "STOP").exists()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL, `No module named 'perennial.cli'`

- [ ] **Step 3: Implement**

```python
from __future__ import annotations

import argparse
import os
import time
from collections import Counter
from pathlib import Path

from perennial.config import load_config
from perennial.gate import Outbox, distress_send, relay_once
from perennial.policy import Policy
from perennial.store import Store

DEFAULT_CONFIG = Path(os.environ.get("PERENNIAL_CONFIG", "~/.perennial/config.toml")).expanduser()


def build(cfg):
    from perennial.executor import Executor
    from perennial.runner import ClaudeRunner
    from perennial.sources import load_sources
    from perennial.supervisor import Supervisor
    from perennial.triage import triage

    store = Store(cfg.store_path)
    policy = Policy(stop_file=cfg.stop_file, autonomy=cfg.autonomy, daily_budget=cfg.daily_budget_usd,
                    run_budget=cfg.run_budget_usd)
    runner = ClaudeRunner()
    cfg.workspaces.mkdir(parents=True, exist_ok=True)
    executor = Executor(runner=runner, policy=policy, workspaces=cfg.workspaces, model=cfg.work_model,
                        run_budget=cfg.run_budget_usd, timeout_s=cfg.run_timeout_s, charter=cfg.charter)
    return Supervisor(store=store, sources=load_sources(cfg), policy=policy, executor=executor,
                      outbox=Outbox(cfg.outbox, policy),
                      triage_fn=lambda t: triage(t, runner, cwd=cfg.workspaces, model=cfg.triage_model, charter=cfg.charter),
                      digest_hour=cfg.digest_hour, name=cfg.name)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="perennial")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tick")
    lp = sub.add_parser("loop")
    lp.add_argument("--every", type=int, default=300)
    sub.add_parser("status")
    sub.add_parser("stop")
    sub.add_parser("start")
    rp = sub.add_parser("relay", help="host side: forward allowlisted outbox messages")
    rp.add_argument("--outbox", type=Path, required=True)
    rp.add_argument("--cli", type=Path, required=True, help="path to distress_call cli.py")
    a = ap.parse_args(argv)

    if a.cmd == "relay":
        print(relay_once(a.outbox, distress_send(a.cli)))
        return 0
    cfg = load_config(a.config)
    if a.cmd == "stop":
        cfg.stop_file.parent.mkdir(parents=True, exist_ok=True)
        cfg.stop_file.write_text("stopped by owner\n")
    elif a.cmd == "start":
        cfg.stop_file.unlink(missing_ok=True)
    elif a.cmd == "status":
        store = Store(cfg.store_path)
        state = "STOPPED" if cfg.stop_file.exists() else "RUNNING"
        counts = Counter(t["status"] for t in store.tasks())
        print(f"{cfg.name}: {state} · spent today ${store.spent_today():.2f}/{cfg.daily_budget_usd:.0f} · {dict(counts)}")
    elif a.cmd == "tick":
        build(cfg).tick()
    elif a.cmd == "loop":
        sv = build(cfg)
        while True:
            try:
                sv.tick()
            except Exception as e:
                sv.store.event("tick_error", error=str(e)[:1000])
            time.sleep(a.every)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run all tests**

Run: `uv run pytest -q`
Expected: 47 passed

- [ ] **Step 5: Commit**

```bash
git add src/perennial/cli.py tests/test_cli.py && git commit -m "feat: cli with tick, loop, status, stop, start, relay"
```

---

### Task 14: Sandbox user, snapshots and launchd

**Files:**
- Create: `deploy/setup-sandbox-user.sh`, `deploy/export-snapshots.sh`, `deploy/launchd/ai.perennial.supervisor.plist`, `deploy/launchd/ai.perennial.host.plist`, `docs/install.md`

- [ ] **Step 1: Write `deploy/setup-sandbox-user.sh`** (the owner runs it once with sudo)

```bash
#!/usr/bin/env bash
# Creates the 'perennial' macOS user and the shared exchange dirs, and locks down the owner's home.
set -euo pipefail
OWNER="${1:?usage: sudo ./setup-sandbox-user.sh <owner-username>}"
SHARED=/Users/Shared/perennial

if ! id perennial >/dev/null 2>&1; then
  sysadminctl -addUser perennial -fullName "Perennial agent" -password - -home /Users/perennial
  createhomedir -c -u perennial >/dev/null
fi
# The owner's home must not be readable by the agent (dotfiles hold secrets).
chmod 700 "/Users/$OWNER"
# inbox: owner writes snapshots, agent reads. outbox: agent writes, owner's relay reads and moves.
mkdir -p "$SHARED/inbox" "$SHARED/outbox"
chown "$OWNER":staff "$SHARED/inbox" && chmod 755 "$SHARED/inbox"
chown perennial:staff "$SHARED/outbox" && chmod 775 "$SHARED/outbox"
echo "done. Next: log in as perennial once and run 'claude' and 'gh auth login' with the BOT account."
```

- [ ] **Step 2: Write `deploy/export-snapshots.sh`** (runs as the owner every 5 minutes)

```bash
#!/usr/bin/env bash
# Copies the todo files passed as arguments into the agent's inbox. Nothing else leaves the owner's home.
set -euo pipefail
INBOX=/Users/Shared/perennial/inbox
for f in "$@"; do
  [ -f "$f" ] && cp "$f" "$INBOX/$(basename "$f").tmp" && mv "$INBOX/$(basename "$f").tmp" "$INBOX/$(basename "$f")"
done
```

- [ ] **Step 3: Write the launchd jobs**

`deploy/launchd/ai.perennial.supervisor.plist` (installed in `/Library/LaunchDaemons`, runs as `perennial`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>ai.perennial.supervisor</string>
  <key>UserName</key><string>perennial</string>
  <key>ProgramArguments</key><array>
    <string>/Users/perennial/perennial/.venv/bin/perennial</string><string>loop</string><string>--every</string><string>300</string>
  </array>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/Users/perennial/.local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
    <key>HOME</key><string>/Users/perennial</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>StandardOutPath</key><string>/Users/perennial/.perennial/supervisor.log</string>
  <key>StandardErrorPath</key><string>/Users/perennial/.perennial/supervisor.log</string>
</dict></plist>
```

`deploy/launchd/ai.perennial.host.plist` (installed in the owner's `~/Library/LaunchAgents`, every 300 s). It runs both host jobs: the snapshot export of the allowlisted files and the relay.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>ai.perennial.host</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>-c</string>
    <string>$HOME/perennial/deploy/export-snapshots.sh "$HOME/notes/Today.md"; $HOME/perennial/.venv/bin/perennial relay --outbox /Users/Shared/perennial/outbox --cli $HOME/distress-call/cli.py</string>
  </array>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
</dict></plist>
```


- [ ] **Step 4: Write `docs/install.md`**

The steps, in order:
1. `sudo deploy/setup-sandbox-user.sh <you>`.
2. As `perennial`: clone the repo to `~/perennial`, `uv sync`, run `claude` once to log in (make sure `ANTHROPIC_API_KEY` is unset), `gh auth login` with the bot account, then copy `config.example.toml` to `~/.perennial/config.toml` and edit it.
3. As the owner: install `ai.perennial.host.plist` and load it.
4. As admin: copy `ai.perennial.supervisor.plist` to `/Library/LaunchDaemons/` and run `sudo launchctl bootstrap system /Library/LaunchDaemons/ai.perennial.supervisor.plist`.
5. Kill switch: `sudo -u perennial perennial stop`.

- [ ] **Step 5: Commit**

```bash
git add deploy docs/install.md && git commit -m "feat: sandbox user, snapshot export, relay and launchd units"
```

---

### Task 15: End-to-end smoke test (manual, on the real machine)

- [ ] **Step 1:** Create a private bot test repo `perennial-sandbox` with one issue labelled `perennial`: "Add a hello.py that prints hello and a test for it".
- [ ] **Step 2:** Run `sudo -u perennial -i perennial tick` twice.
  Expected: `perennial status` shows the issue `done`. A PR exists on the test repo, with `hello.py`, a test and `RESULT.md` in the body.
- [ ] **Step 3:** Add `- [ ] Write a 200-word summary of the Dots launch` to a test Markdown file. Export it with `deploy/export-snapshots.sh`, then tick.
  Expected: the task is `done` and the workspace has `RESULT.md`.
- [ ] **Step 4:** Add `- [ ] Pay the electricity bill` and tick.
  Expected: the task is `skipped` or `needs_human` and is never executed.
- [ ] **Step 5:** Kill-switch check: `perennial stop`, tick. Expected: an event `stopped`, and no new runs.
- [ ] **Step 6:** Isolation check, as `perennial`: `cat /Users/<owner>/.zshrc`. Expected: `Permission denied`.
- [ ] **Step 7:** Digest: set `digest_hour` to the current hour and tick, then run the host relay.
  Expected: one Telegram message with label `perennial-digest`.

---

## Self-review

- **Spec coverage:** always-on (Task 14, launchd KeepAlive); reads todos (Tasks 5–6); acts alone (Tasks 9, 11, 12); reports (Tasks 10, 12); kill switch and budget (Tasks 7, 12, 13); sandbox (Task 14); public repo with private config (Task 1 `.gitignore`, Task 3 config in `~/.perennial`). Ideas and builds are phase 2 by design.
- **Known gaps carried to phase 2:** the approval gate for L3 actions; idea generation; true spend accounting for timed-out runs; a UTC/local digest boundary.

## Deviations during implementation (1 Oct 2026)

- `Config.outbox` can point outside the agent's home (`outbox = "/Users/Shared/perennial/outbox"`). The owner's relay cannot read `/Users/perennial`. A test was added.
- `Store.spent_today()` now also counts triage spend (logged on `triaged` events). Before this, the budget ignored triage calls. A test was added.
- The supervisor plist wraps the loop in `caffeinate -i`.
- Live smoke (Task 15, steps 3–5) passed on a dev machine as the owner user, not yet as the sandbox user. The run triaged 2 todos: it did the code task (hello.py plus a passing test, $0.21) and skipped the errand. The digest went through the relay, and the kill switch blocked the next tick. Steps 1–2, 6 and 7 need the sandbox user and the GitHub App.
