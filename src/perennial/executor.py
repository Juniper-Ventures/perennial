from __future__ import annotations

import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

from perennial.models import RunOutput


def run_git(*args, cwd=None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=300).stdout


def run_gh(*args) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, timeout=300).stdout


def work_prompt(task: dict) -> str:
    return (
        f"Task: {task['title']}\nSource: {task['source']} {task.get('url', '')}\nContext:\n{task['body'][:4000]}\n\n"
        "Work only inside the current directory. Finish the task end to end. Write tests where code is involved and run them.\n"
        "When done, write RESULT.md: what you did, how you verified it, and what is left. Keep it under 300 words.\n"
        "Do not create accounts, send messages, publish, or spend money. If the task needs that, stop and say so in RESULT.md."
    )


class Executor:
    def __init__(self, runner, policy, workspaces: Path, model: str, run_budget: float, timeout_s: int,
                 charter: str, git=run_git, gh=run_gh):
        self.runner, self.policy, self.workspaces = runner, policy, Path(workspaces)
        self.model, self.run_budget, self.timeout_s, self.charter = model, run_budget, timeout_s, charter
        self.git, self.gh = git, gh

    def execute(self, task: dict) -> tuple[RunOutput, Path]:
        self.policy.require("build")
        ws = self.workspaces / task["id"]
        if ws.exists():
            shutil.rmtree(ws)
        is_gh = task["source"].startswith("github:")
        if is_gh:
            repo = task["source"].split(":", 1)[1]
            self.workspaces.mkdir(parents=True, exist_ok=True)
            self.gh("repo", "clone", repo, str(ws))
            self.git("checkout", "-b", f"perennial/{task['id']}", cwd=ws)
        else:
            ws.mkdir(parents=True)
        out = self.runner.run(work_prompt(task), cwd=ws, model=self.model, budget_usd=self.run_budget,
                              timeout_s=self.timeout_s, system=self.charter)
        if out.ok and is_gh:
            out = self._ship(task, ws, out)
        return out, ws

    def _ship(self, task: dict, ws: Path, out: RunOutput) -> RunOutput:
        if not self.git("status", "--porcelain", cwd=ws).strip():
            return replace(out, summary=out.summary + "\n(no changes to ship)")
        self.policy.require("push_own")
        self.git("add", "-A", cwd=ws)
        self.git("commit", "-m", f"perennial: {task['title'][:60]}", cwd=ws)
        self.git("push", "-u", "origin", f"perennial/{task['id']}", cwd=ws)
        self.policy.require("open_pr")
        result = (ws / "RESULT.md").read_text()[:3000] if (ws / "RESULT.md").exists() else out.summary[:3000]
        url = self.gh("pr", "create", "--repo", task["source"].split(":", 1)[1], "--head", f"perennial/{task['id']}",
                      "--title", f"perennial: {task['title'][:60]}", "--body", f"Closes {task.get('url', '')}\n\n{result}").strip()
        return replace(out, summary=f"{out.summary}\nPR: {url}")
