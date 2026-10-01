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


def test_spent_today_includes_triage_cost(tmp_path):
    s = Store(tmp_path / "s.sqlite")
    s.event("triaged", task="x", decision="do", cost=0.25)
    s.event("source_error", source="y", error="z")
    assert s.spent_today() == 0.25


def test_ideas_queue_best_and_ignore_duplicates(tmp_path):
    s = Store(tmp_path / "s.sqlite")
    s.add_ideas([
        {"title": "Weak", "pitch": "p", "value": 2, "effort": 4, "novelty": 2},
        {"title": "Strong", "pitch": "p", "value": 5, "effort": 1, "novelty": 4},
        {"title": "Strong", "pitch": "dup", "value": 5, "effort": 1, "novelty": 5},
    ])
    assert sorted(s.idea_titles()) == ["Strong", "Weak"]
    best = s.queue_best_idea()
    assert best["title"] == "Strong"
    assert [i["title"] for i in s.ideas(status="queued")] == ["Strong"]
    assert s.queue_best_idea()["title"] == "Weak"
    assert s.queue_best_idea() is None


def test_approval_lifecycle(tmp_path):
    s = Store(tmp_path / "s.sqlite")
    s.add_approval("ap1", task_id="t1", action="publish", payload={"repo": "o/r"})
    [a] = s.approvals(status="pending")
    assert a["payload"] == {"repo": "o/r"} and a["action"] == "publish"
    s.set_approval("ap1", "approved")
    assert s.approvals(status="pending") == [] and s.approvals(status="approved")[0]["id"] == "ap1"
