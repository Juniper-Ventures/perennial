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
