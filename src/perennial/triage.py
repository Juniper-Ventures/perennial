from __future__ import annotations

import json
import re
from pathlib import Path

from perennial.models import Task, Triage

TRIAGE_BUDGET_USD = 0.10
JSON_OBJ = re.compile(r"\{.*?\}", re.S)

RULES = """Decide if you can move this task forward ALONE inside your own sandbox computer.
- "do": you can finish it, OR you can do the preparation so that only the owner's final step is left:
  research, a plan, a comparison, a checklist, or the draft text of a message the owner will send.
  Most todos that "need the owner" still have preparation you can do: choose "do" for those. Examples:
  a dinner or an invite -> draft the invitation, propose dates and a venue; setting up an entity, account
  or program -> research the options and write the plan; a decision -> lay out the options with a recommendation.
- "ask": only when there is nothing useful to prepare without the owner's input first. Then the reason
  must be the one question the owner should answer (it is sent to them as is).
- "skip": it is a personal errand or physical task (post office, calls, travel), or not actionable.
- "skip" also when the task is outside the role your instructions above describe, even if you could do it.
  A teammate with that role will take it. Only "do" tasks that fit your role.
You may never: spend money, send email or messages as the owner, use the owner's credentials, or delete outside your sandbox.
Answer ONLY with JSON: {"decision":"do|ask|skip","value":1-5,"effort":1-5,"reason":"one sentence"}"""


def triage_prompt(task: Task, charter: str) -> str:
    return f"{charter}\n\n{RULES}\n\nTask source: {task.source}\nTitle: {task.title}\nContext:\n{task.body[:2000]}"


def _clamp(v, lo=1, hi=5) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return 3


def parse_triage(text: str) -> Triage:
    for m in JSON_OBJ.finditer(text or ""):
        try:
            d = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if d.get("decision") in ("do", "ask", "skip"):
            return Triage(d["decision"], _clamp(d.get("value")), _clamp(d.get("effort")), str(d.get("reason", ""))[:300])
    return Triage("ask", 1, 5, "could not parse triage output")


class TriageError(RuntimeError):
    """The triage call itself failed (auth, network, CLI). The task must stay untriaged."""


def triage(task: Task, runner, cwd: Path, model: str, charter: str) -> tuple[Triage, float]:
    out = runner.run(triage_prompt(task, charter), cwd=cwd, model=model, budget_usd=TRIAGE_BUDGET_USD,
                     timeout_s=180, system="You are a careful triage step. Output JSON only.")
    if not out.ok:
        raise TriageError(f"triage run failed: {out.summary[:300]}")
    return parse_triage(out.summary), out.cost_usd
