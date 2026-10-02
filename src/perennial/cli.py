from __future__ import annotations

import argparse
import os
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from perennial.claims import Claims
from perennial.config import load_config
from perennial.gate import Approvals, Outbox, distress_ask, distress_send, relay_once
from perennial.policy import Policy
from perennial.store import Store

DEFAULT_CONFIG = Path(os.environ.get("PERENNIAL_CONFIG", "~/.perennial/config.toml")).expanduser()


def read_context(paths) -> str:
    parts = []
    for p in paths or []:
        f = Path(p).expanduser()
        if f.exists():
            parts.append(f"## {f.name}\n{f.read_text()[:6000]}")
    return "\n\n".join(parts)


def build(cfg):
    from perennial.executor import Executor, run_gh
    from perennial.ideas import IdeaSource, generate_ideas
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
                        run_budget=cfg.run_budget_usd, timeout_s=cfg.run_timeout_s, charter=cfg.charter,
                        builds_owner=cfg.builds_owner)

    def ideate(existing):
        return generate_ideas(runner, cwd=cfg.workspaces, model=cfg.work_model, charter=cfg.charter,
                              context=read_context(cfg.idea_context), existing=existing, n=cfg.ideas_per_day,
                              budget_usd=min(1.0, cfg.run_budget_usd))

    return Supervisor(store=store, sources=load_sources(cfg) + [IdeaSource(store)], policy=policy, executor=executor,
                      outbox=Outbox(cfg.outbox, policy),
                      triage_fn=lambda t: triage(t, runner, cwd=cfg.workspaces, model=cfg.triage_model, charter=cfg.charter),
                      digest_hour=cfg.digest_hour, name=cfg.name,
                      ideate_fn=ideate if cfg.ideas_per_day > 0 else None, idea_hour=cfg.idea_hour,
                      approvals=Approvals(cfg.approvals), gh=run_gh,
                      claims=Claims(cfg.claims) if cfg.claims else None,
                      post_results=cfg.post_results_to_root)


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
    rp.add_argument("--approvals", type=Path, default=None, help="dir for owner answers; enables approval requests")
    rp.add_argument("--root-parent", default=None, help="root page id that result pages go under; needs ROOT_API_KEY")
    rp.add_argument("--root-actor", default="perennial")
    rx = sub.add_parser("export-root", help="host side: write a root inbox page as a Markdown checklist")
    rx.add_argument("--page", required=True)
    rx.add_argument("--out", type=Path, required=True)
    sub.add_parser("ideate", help="run ideation now and queue the best idea")
    xp = sub.add_parser("export-airtable", help="host side: write an Airtable todo table as a Markdown checklist")
    xp.add_argument("--base", required=True)
    xp.add_argument("--table", required=True)
    xp.add_argument("--out", type=Path, required=True)
    xp.add_argument("--owner-email", default=None)
    dp = sub.add_parser("dashboard", help="read-only status page on 127.0.0.1")
    dp.add_argument("--port", type=int, default=8787)
    a = ap.parse_args(argv)

    if a.cmd == "export-root":
        from perennial.root import export_inbox
        print(export_inbox(a.page, a.out))
        return 0
    if a.cmd == "export-airtable":
        from perennial.airtable import export
        print(export(a.base, a.table, a.out, owner_email=a.owner_email))
        return 0
    if a.cmd == "relay":
        ask = distress_ask(a.cli, a.approvals) if a.approvals else None
        post_root = None
        if a.root_parent:
            from perennial.root import root_poster
            post_root = root_poster(a.root_parent, a.root_actor)
        print(relay_once(a.outbox, distress_send(a.cli), ask=ask, post_root=post_root))
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
    elif a.cmd == "ideate":
        sv = build(cfg)
        sv.store.put("idea_date", "")
        sv.idea_hour = 0
        sv._maybe_ideate(datetime.now())
        print([i["title"] for i in sv.store.ideas(status="queued")])
    elif a.cmd == "dashboard":
        from perennial.dashboard import serve
        print(f"http://127.0.0.1:{a.port}")
        serve(lambda: Store(cfg.store_path), cfg, a.port)
    elif a.cmd == "tick":
        build(cfg).tick()
    elif a.cmd == "loop":
        sv = build(cfg)
        last = sv.store.last_event_id()
        while True:
            try:
                sv.tick()
            except Exception as e:
                sv.store.event("tick_error", error=str(e)[:1000])
            # Echo new events to stdout, so the owner-readable launchd log shows what happened.
            for ev in sv.store.events_after(last):
                print(f"{ev['ts']} {cfg.name} {ev['kind']} {ev['data']}", flush=True)
                last = ev["id"]
            time.sleep(a.every)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
