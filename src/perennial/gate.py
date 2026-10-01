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
