from __future__ import annotations

from datetime import datetime
from pathlib import Path

from perennial.models import Task


def local_day(iso: str | None) -> str:
    """Store timestamps are UTC ISO strings; the digest works in local days."""
    try:
        return datetime.fromisoformat(iso).astimezone().date().isoformat()
    except (TypeError, ValueError):
        return ""


class Supervisor:
    def __init__(self, store, sources, policy, executor, outbox, triage_fn, digest_hour: int, name: str,
                 ideate_fn=None, idea_hour: int = 3, approvals=None, gh=None, claims=None,
                 post_results: bool = False):
        self.store, self.sources, self.policy = store, sources, policy
        self.executor, self.outbox, self.triage_fn = executor, outbox, triage_fn
        self.digest_hour, self.name = digest_hour, name
        self.ideate_fn, self.idea_hour, self.approvals, self.gh = ideate_fn, idea_hour, approvals, gh
        self.claims = claims
        self.post_results = post_results

    def tick(self, now: datetime | None = None) -> None:
        now = now or datetime.now()
        if self.policy.stopped():
            self.store.event("stopped")
            return
        self._refresh()
        self._triage_new()
        self._run_one()
        self._apply_approvals()
        self._maybe_ideate(now)
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
            try:
                tr, cost = self.triage_fn(task)
            except Exception as e:  # keep the task 'new' so the next tick retries it
                self.store.event("triage_error", task=row["id"], error=str(e)[:500])
                return
            self.store.set_triage(row["id"], tr)
            self.store.event("triaged", task=row["id"], decision=tr.decision, cost=cost)

    def _run_one(self) -> None:
        if self.policy.stopped() or not self.policy.can_spend(self.store):
            return
        task = self._claim_next()
        if not task:
            return
        rid = self.store.start_run(task["id"], workspace="")
        self.store.event("run_started", task=task["id"], title=task["title"][:100])
        try:
            out, ws = self.executor.execute(task)
        except Exception as e:
            self.store.finish_run(rid, ok=False, cost_usd=0.0, summary=f"executor error: {e}"[:2000])
            self.store.event("run_finished", task=task["id"], ok=False, error=str(e)[:500])
            if self.claims:
                self.claims.release(task["id"], self.name)
            return
        result = Path(ws) / "RESULT.md"
        result_text = result.read_text()[:20000] if result.exists() else ""
        nxt = next((ln.strip() for ln in result_text.splitlines() if ln.strip().lower().startswith("next step for the owner:")), "")
        self.store.finish_run(rid, ok=out.ok, cost_usd=out.cost_usd,
                              summary=f"{out.summary}\n{nxt}\nworkspace: {ws}" if nxt else f"{out.summary}\nworkspace: {ws}")
        self.store.event("run_finished", task=task["id"], ok=out.ok, cost=out.cost_usd)
        if out.ok and self.post_results:
            body = result_text or out.summary
            self.outbox.root_page(f"{self.name}: {task['title'][:100]}", f"{body}\n\n---\nSource: {task['source']} {task.get('url', '')}")
        if not out.ok and self.claims and self.store.get_task(task["id"])["status"] != "parked":
            self.claims.release(task["id"], self.name)  # let another perennial try
        repo = (out.raw or {}).get("publish")
        if out.ok and repo and self.policy.autonomy >= 3:
            aid = f"pub-{task['id']}"
            self.store.add_approval(aid, task_id=task["id"], action="publish", payload={"repo": repo})
            first = (out.summary or "").strip().splitlines()[0][:300] if out.summary else ""
            self.outbox.request_approval(aid, f"{self.name} built {repo} (private). Make it public?\n{first}")

    def _claim_next(self) -> dict | None:
        for task in self.store.ready_tasks():
            if not self.claims or self.claims.claim(task["id"], self.name):
                return task
            self.store.set_status(task["id"], "claimed")
        return None

    def _apply_approvals(self) -> None:
        if not self.approvals:
            return
        for ap in self.store.approvals(status="pending"):
            answer = self.approvals.answer(ap["id"])
            if answer is None:
                continue
            if not answer:
                self.store.set_approval(ap["id"], "denied")
                self.store.event("approval_denied", id=ap["id"])
                continue
            try:
                self.policy.require(ap["action"], approved=True)
                if ap["action"] == "publish":
                    self.gh("repo", "edit", ap["payload"]["repo"], "--visibility", "public",
                            "--accept-visibility-change-consequences")
                self.store.set_approval(ap["id"], "done")
                self.store.event("approval_applied", id=ap["id"], action=ap["action"])
            except Exception as e:
                self.store.set_approval(ap["id"], "failed")
                self.store.event("approval_failed", id=ap["id"], error=str(e)[:500])

    def _maybe_ideate(self, now: datetime) -> None:
        day = now.date().isoformat()
        if not self.ideate_fn or now.hour < self.idea_hour or self.store.get("idea_date") == day:
            return
        if self.policy.stopped() or not self.policy.can_spend(self.store):
            return
        ideas, cost = self.ideate_fn(self.store.idea_titles())
        added = self.store.add_ideas(ideas)
        best = self.store.queue_best_idea()
        self.store.event("ideated", added=added, queued=best["title"] if best else None, cost=cost)
        self.store.put("idea_date", day)

    def _maybe_digest(self, now: datetime) -> None:
        day = now.date().isoformat()
        if now.hour < self.digest_hour or self.store.get("digest_date") == day:
            return
        runs = self.store.runs_since(day)
        lines = [f"{self.name} — {day}: {len(runs)} runs, ${sum(r['cost_usd'] for r in runs):.2f}"]
        for r in runs:
            mark = "done" if r["ok"] else "failed"
            summary = r["summary"] or ""
            lines.append(f"- {mark}: {r['title'][:80]} — {summary.splitlines()[0][:120] if summary else ''}")
            nxt = next((ln.split(":", 1)[1].strip() for ln in summary.splitlines()
                        if ln.lower().startswith("next step for the owner:")), "")
            if nxt:
                lines.append(f"  → you: {nxt[:200]}")
        # Only todos that newly need the owner today; the standing list is on the dashboard, not repeated daily.
        asks = [a for a in self.store.tasks(status="needs_human") if local_day(a["updated_at"]) == day]
        if asks:
            lines.append(f"Needs you ({len(asks)}):")
            lines += [f"- {a['title'][:60]} — {(a['reason'] or '')[:160]}" for a in asks[:5]]
        today_ideas = [i for i in self.store.ideas() if i["created_at"][:10] == day]
        if today_ideas:
            queued = [i["title"] for i in self.store.ideas(status="queued")]
            lines.append(f"Ideas today: {len(today_ideas)}" + (f" · building: {queued[-1][:60]}" if queued else ""))
        pending = self.store.approvals(status="pending")
        if pending:
            lines.append(f"Waiting for your approval ({len(pending)}): " + "; ".join(
                f"{a['action']} {a['payload'].get('repo', '')}" for a in pending[:5]))
        parked = self.store.tasks(status="parked")
        if parked:
            lines.append(f"Parked after 3 failures: " + "; ".join(p["title"][:60] for p in parked[:5]))
        if len(lines) > 1:  # nothing happened and nothing is waiting: no message
            self.outbox.notify("\n".join(lines), label="perennial-digest")
        self.store.put("digest_date", day)
