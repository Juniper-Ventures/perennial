"""Nightly ideation: the perennial proposes its own projects; the best one becomes a build task."""
from __future__ import annotations

import json
import re

from perennial.models import Task

ARRAY = re.compile(r"\[.*\]", re.S)

RULES = """Propose {n} NEW software projects you can build ALONE in one session inside your own sandbox computer:
a working tool, library, CLI, small web app, dataset or analysis, with tests and a README.
They must be useful to the owner given the context, and different from the existing ideas.
Do not propose anything that needs money, accounts, other people, the owner's credentials or publishing.
Answer ONLY with a JSON array of objects:
[{{"title": "short name", "pitch": "2-4 sentences: what it does and why it matters", "value": 1-5, "effort": 1-5, "novelty": 1-5}}]"""


def ideation_prompt(charter: str, context: str, existing: list[str], n: int) -> str:
    ex = "\n".join(f"- {t}" for t in existing[-50:]) or "(none)"
    return f"{charter}\n\n{RULES.format(n=n)}\n\nContext from the owner:\n{context[:12000] or '(none)'}\n\nExisting ideas:\n{ex}"


def _clamp(v) -> int:
    try:
        return max(1, min(5, int(v)))
    except (TypeError, ValueError):
        return 3


def parse_ideas(text: str, n: int) -> list[dict]:
    m = ARRAY.search(text or "")
    if not m:
        return []
    try:
        raw = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out = []
    for i in raw if isinstance(raw, list) else []:
        if not isinstance(i, dict) or not str(i.get("title", "")).strip() or not str(i.get("pitch", "")).strip():
            continue
        out.append({"title": str(i["title"]).strip()[:120], "pitch": str(i["pitch"]).strip()[:1500],
                    "value": _clamp(i.get("value")), "effort": _clamp(i.get("effort")), "novelty": _clamp(i.get("novelty"))})
    return out[:n]


def generate_ideas(runner, cwd, model: str, charter: str, context: str, existing: list[str], n: int,
                   budget_usd: float) -> tuple[list[dict], float]:
    out = runner.run(ideation_prompt(charter, context, existing, n), cwd=cwd, model=model, budget_usd=budget_usd,
                     timeout_s=900, system="You are the ideation step. Output a JSON array only.")
    return (parse_ideas(out.summary, n) if out.ok else []), out.cost_usd


class IdeaSource:
    source = "idea:local"

    def __init__(self, store):
        self.store = store

    def fetch(self) -> list[Task]:
        return [Task.new(source=self.source, ext_id=i["id"], title=i["title"],
                         body=f"Build this idea end to end:\n{i['pitch']}")
                for i in self.store.ideas(status="queued")]
