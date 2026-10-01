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
