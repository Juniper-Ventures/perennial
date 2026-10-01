from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Protocol

from perennial.models import RunOutput


class Runner(Protocol):
    def run(self, prompt: str, cwd: Path, model: str, budget_usd: float, timeout_s: int, system: str) -> RunOutput: ...


class ClaudeRunner:
    """Headless Claude Code. Runs inside the sandbox user, so bypassPermissions is bounded by the OS user."""

    def __init__(self, binary: str = "claude"):
        self.binary = binary

    def run(self, prompt, cwd, model, budget_usd, timeout_s, system) -> RunOutput:
        cmd = [self.binary, "-p", prompt, "--output-format", "json", "--model", model,
               "--max-budget-usd", f"{budget_usd:g}", "--permission-mode", "bypassPermissions",
               "--append-system-prompt", system]
        try:
            proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return RunOutput(ok=False, cost_usd=0.0, summary=f"timeout after {timeout_s}s")
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return RunOutput(ok=False, cost_usd=0.0, summary=(proc.stderr or proc.stdout)[-2000:])
        ok = proc.returncode == 0 and not data.get("is_error", False)
        return RunOutput(ok=ok, cost_usd=float(data.get("total_cost_usd") or 0), summary=str(data.get("result", ""))[-4000:], raw=data)
