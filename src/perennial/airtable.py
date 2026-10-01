"""Host-side export of an Airtable todo table into a Markdown checklist the perennials can read."""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

DONE = ("done", "complete", "completed", "cancelled", "canceled")


def _owner_email(v) -> str:
    if isinstance(v, dict):
        return str(v.get("email", "")).lower()
    return ""


def records_to_markdown(records: list[dict], title: str, task_field: str = "Task", status_field: str = "Status",
                        deadline_field: str = "Deadline", next_field: str = "Next Step", owner_field: str = "NS Owner",
                        owner_email: str | None = None) -> str:
    lines = [f"# {title}"]
    for r in records:
        f = r.get("fields", {})
        task = str(f.get(task_field, "")).strip()
        if not task or str(f.get(status_field, "")).strip().lower() in DONE:
            continue
        if owner_email and _owner_email(f.get(owner_field)) != owner_email.lower():
            continue
        due = f" (due {f[deadline_field]})" if f.get(deadline_field) else ""
        lines.append(f"- [ ] {' '.join(task.split())}{due}")
        nxt = [s.strip(" -*\t") for s in str(f.get(next_field, "")).splitlines() if s.strip(" -*\t")]
        if nxt:
            lines.append("  Next: " + "; ".join(nxt[:5]))
    return "\n".join(lines) + "\n"


def fetch_records(base: str, table: str, token: str) -> list[dict]:
    out, offset = [], None
    while True:
        q = {"pageSize": "100"} | ({"offset": offset} if offset else {})
        url = f"https://api.airtable.com/v0/{base}/{urllib.parse.quote(table)}?{urllib.parse.urlencode(q)}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        data = json.load(urllib.request.urlopen(req, timeout=60))
        out += data.get("records", [])
        offset = data.get("offset")
        if not offset:
            return out


def export(base: str, table: str, out: Path, owner_email: str | None = None) -> int:
    token = os.environ["AIRTABLE_PAT"]
    md = records_to_markdown(fetch_records(base, table, token), title=table, owner_email=owner_email)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(md)
    tmp.rename(out)
    return md.count("\n- [ ]") + md.startswith("- [ ]")
