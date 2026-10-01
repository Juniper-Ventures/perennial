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


class BuildEx:
    def __init__(self):
        self.ran = []

    def execute(self, task):
        self.ran.append(task["title"])
        return RunOutput(ok=True, cost_usd=0.5, summary="built it", raw={"publish": "Org/perennial-x"}), "/ws"


class ApprovalBox(Outbox):
    def __init__(self):
        super().__init__()
        self.requests = []

    def request_approval(self, rid, message):
        self.requests.append((rid, message))


class FakeApprovals:
    def __init__(self):
        self.answers = {}

    def answer(self, rid):
        return self.answers.get(rid)


def make3(tmp_path, sources, ideate_fn=None, autonomy=3):
    from perennial.ideas import IdeaSource

    pol = Policy(stop_file=tmp_path / "STOP", autonomy=autonomy, daily_budget=10, run_budget=2)
    store = Store(tmp_path / "s.sqlite")
    gh_calls = []
    sv = Supervisor(store=store, sources=sources + [IdeaSource(store)], policy=pol, executor=BuildEx(),
                    outbox=ApprovalBox(), triage_fn=lambda task: (Triage("do", 4, 2, ""), 0.01), digest_hour=23,
                    name="ember", ideate_fn=ideate_fn, idea_hour=3, approvals=FakeApprovals(),
                    gh=lambda *a: gh_calls.append(a) or "")
    return sv, gh_calls


def test_nightly_ideation_queues_best_idea_once_per_day_then_builds_it(tmp_path):
    calls = []

    def ideate(existing):
        calls.append(existing)
        return [{"title": "Linter", "pitch": "p", "value": 5, "effort": 1, "novelty": 5},
                {"title": "Meh", "pitch": "p", "value": 1, "effort": 5, "novelty": 1}], 0.2

    sv, _ = make3(tmp_path, [], ideate)
    sv.tick(now=datetime(2026, 10, 2, 2))  # before idea_hour
    assert calls == []
    sv.tick(now=datetime(2026, 10, 2, 3, 1))
    sv.tick(now=datetime(2026, 10, 2, 3, 6))  # idea becomes a task, triaged and built
    sv.tick(now=datetime(2026, 10, 2, 4))
    assert len(calls) == 1
    assert sv.executor.ran == ["Linter"]
    assert sv.store.spent_today() >= 0.2


def test_build_requests_publish_and_applies_only_after_yes(tmp_path):
    sv, gh_calls = make3(tmp_path, [Src([t("build x")])])
    sv.tick(now=datetime(2026, 10, 2, 9))
    [(rid, msg)] = sv.outbox.requests
    assert rid.startswith("pub-") and "Make it public?" in msg
    sv.tick(now=datetime(2026, 10, 2, 9, 5))
    assert gh_calls == []  # no answer yet
    sv.approvals.answers[rid] = True
    sv.tick(now=datetime(2026, 10, 2, 9, 10))
    assert gh_calls == [("repo", "edit", "Org/perennial-x", "--visibility", "public",
                         "--accept-visibility-change-consequences")]
    assert sv.store.approvals(status="done")[0]["id"] == rid


def test_denied_publish_does_nothing(tmp_path):
    sv, gh_calls = make3(tmp_path, [Src([t("build y")])])
    sv.tick(now=datetime(2026, 10, 2, 9))
    rid = sv.outbox.requests[0][0]
    sv.approvals.answers[rid] = False
    sv.tick(now=datetime(2026, 10, 2, 9, 5))
    assert gh_calls == [] and sv.store.approvals(status="denied")[0]["id"] == rid


def test_no_publish_request_below_autonomy_three(tmp_path):
    sv, _ = make3(tmp_path, [Src([t("build z")])], autonomy=2)
    sv.tick(now=datetime(2026, 10, 2, 9))
    assert sv.outbox.requests == [] and sv.store.approvals() == []


def test_two_perennials_never_run_the_same_task(tmp_path):
    from perennial.claims import Claims

    tasks = [t("one"), t("two"), t("three")]
    sups = []
    for name in ("ember", "sage"):
        pol = Policy(stop_file=tmp_path / name / "STOP", autonomy=2, daily_budget=10, run_budget=1)
        sups.append(Supervisor(store=Store(tmp_path / name / "s.sqlite"), sources=[Src(tasks)], policy=pol,
                               executor=Ex(), outbox=Outbox(), triage_fn=lambda task: (Triage("do", 3, 3, ""), 0),
                               digest_hour=23, name=name, claims=Claims(tmp_path / "claims.sqlite")))
    for minute in range(4):
        for sv in sups:
            sv.tick(now=datetime(2026, 10, 2, 9, minute))
    ran = sups[0].executor.ran + sups[1].executor.ran
    assert sorted(ran) == ["one", "three", "two"]
    assert sups[0].executor.ran and sups[1].executor.ran


class FailEx(Ex):
    def execute(self, task):
        self.ran.append(task["title"])
        return RunOutput(ok=False, cost_usd=0.1, summary="nope"), "/ws"


def test_failed_run_releases_claim(tmp_path):
    from perennial.claims import Claims

    claims = Claims(tmp_path / "claims.sqlite")
    pol = Policy(stop_file=tmp_path / "STOP", autonomy=2, daily_budget=10, run_budget=1)
    sv = Supervisor(store=Store(tmp_path / "s.sqlite"), sources=[Src([t("hard")])], policy=pol, executor=FailEx(),
                    outbox=Outbox(), triage_fn=lambda task: (Triage("do", 3, 3, ""), 0), digest_hour=23,
                    name="ember", claims=claims)
    sv.tick(now=datetime(2026, 10, 2, 9))
    tid = sv.store.tasks()[0]["id"]
    assert claims.owner_of(tid) is None
