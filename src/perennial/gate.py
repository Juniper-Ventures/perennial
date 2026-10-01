"""The only path out of the sandbox.

Sandbox side: Outbox writes JSON requests into a directory the owner's user can read.
Host side: relay_once() runs as the owner. It forwards ONLY allowlisted kinds to the owner's
existing notifier (distress_call CLI), so the sandbox never holds messaging credentials.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from perennial.policy import Blocked

ALLOWED_KINDS = {"notify", "approve", "root_page"}
APPROVE_WORDS = ("yes", "ja", "y", "ok", "approve", "approved", "godkend", "godkendt")
APPROVAL_TIMEOUT_S = 900
MAX_LEN = 3500


class Outbox:
    def __init__(self, path: Path, policy):
        self.path, self.policy = Path(path), policy

    def notify(self, message: str, label: str) -> Path:
        self.policy.require("notify_owner")
        return self._write({"kind": "notify", "label": label, "message": message})

    def root_page(self, title: str, markdown: str) -> Path:
        """Post a result page into the perennial's own root area (the relay fixes the parent page)."""
        self.policy.require("post_own_space")
        return self._write({"kind": "root_page", "title": title[:150], "message": markdown[:20000]})

    def request_approval(self, req_id: str, message: str) -> Path:
        """Ask the owner to approve an L3 action. Only meaningful at autonomy 3."""
        if self.policy.autonomy < 3:
            raise Blocked("approval requests need autonomy L3")
        self.policy.require("notify_owner")
        return self._write({"kind": "approve", "id": req_id, "message": message})

    def _write(self, req: dict) -> Path:
        self.path.mkdir(parents=True, exist_ok=True)
        f = self.path / f"{int(time.time())}-{uuid.uuid4().hex[:8]}.json"
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(req))
        tmp.rename(f)  # atomic: the relay never reads a half-written file
        return f


class Approvals:
    """Sandbox side: read the owner's answers that the relay wrote into a shared dir."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def answer(self, req_id: str) -> bool | None:
        f = self.path / f"{req_id}.txt"
        if not f.exists():
            return None
        words = re.findall(r"[a-zæøå]+", f.read_text().strip().lower())
        return bool(words) and words[0] in APPROVE_WORDS


def distress_send(cli: Path) -> Callable[[str, str], None]:
    def send(message: str, label: str) -> None:
        subprocess.run(["python3", str(cli), message, "--label", label], check=True, timeout=60)
    return send


def distress_ask(cli: Path, approvals: Path) -> Callable[[str, str, str], None]:
    """Spawn a detached `cli --wait` per approval; its stdout (the owner's reply) lands in approvals/<id>.txt."""
    def ask(message: str, label: str, req_id: str) -> None:
        Path(approvals).mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_-]", "", req_id)[:64]
        env = os.environ | {"P_CLI": str(cli), "P_MSG": message, "P_LABEL": label, "P_TIMEOUT": str(APPROVAL_TIMEOUT_S),
                            "P_TMP": str(Path(approvals) / f".{safe}.tmp"), "P_OUT": str(Path(approvals) / f"{safe}.txt")}
        script = 'python3 "$P_CLI" "$P_MSG" --wait --timeout "$P_TIMEOUT" --label "$P_LABEL" > "$P_TMP" 2>/dev/null; mv "$P_TMP" "$P_OUT"'
        subprocess.Popen(["bash", "-c", script], env=env, start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return ask


def relay_once(outbox: Path, send: Callable[[str, str], None],
               ask: Callable[[str, str, str], None] | None = None,
               post_root: Callable[[str, str], str] | None = None) -> int:
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
        if ok and req["kind"] == "approve" and (ask is None or not isinstance(req.get("id"), str)):
            ok = False
        if ok and req["kind"] == "root_page" and (post_root is None or not isinstance(req.get("title"), str)):
            ok = False
        if not ok:
            shutil.move(f, outbox / "rejected" / f.name)
            continue
        if req["kind"] == "root_page":
            post_root(req["title"][:150], req["message"][:20000])
        elif req["kind"] == "approve":
            ask(f"{req['message'][:MAX_LEN - 60]}\nReply YES to approve, anything else to deny.", "perennial-approve", req["id"])
        else:
            send(req["message"][:MAX_LEN], str(req.get("label", "perennial"))[:40])
        shutil.move(f, outbox / "sent" / f.name)
        n += 1
    return n
