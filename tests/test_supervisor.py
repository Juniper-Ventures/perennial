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
