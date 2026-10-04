from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

from perennial.models import RunOutput


def run_git(*args, cwd=None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=300).stdout


def run_gh(*args) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, timeout=300).stdout


IDENT = ("-c", "user.name=perennial", "-c", "user.email=perennial@users.noreply.github.com")


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "build"


def work_prompt(task: dict) -> str:
    return (
        f"Task: {task['title']}\nSource: {task['source']} {task.get('url', '')}\nContext:\n{task['body'][:4000]}\n\n"
        "Work only inside the current directory. Move the task as far forward as you can on your own. Write tests where code is involved and run them.\n"
        "If the last step needs the owner (a decision, a message to a person, an account, publishing, money), do all the "
        "preparation (research, plan, draft text ready to send) and stop there.\n"
        "When done, write RESULT.md: what you did, how you verified it, and what is left. Keep it under 300 words. "
        "If the owner must act, end RESULT.md with a line 'Next step for the owner: <one concrete action>'.\n"
        "Do not create accounts, send messages, publish, or spend money."
    )


class Executor:
    def __init__(self, runner, policy, workspaces: Path, model: str, run_budget: float, timeout_s: int,
                 charter: str, git=run_git, gh=run_gh, builds_owner: str = ""):
        self.runner, self.policy, self.workspaces = runner, policy, Path(workspaces)
        self.model, self.run_budget, self.timeout_s, self.charter = model, run_budget, timeout_s, charter
        self.git, self.gh, self.builds_owner = git, gh, builds_owner

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
        is_idea = task["source"].startswith("idea:")
        if is_idea:
            self.git("init", "-q", cwd=ws)
        out = self.runner.run(work_prompt(task), cwd=ws, model=self.model, budget_usd=self.run_budget,
                              timeout_s=self.timeout_s, system=self.charter)
        if out.ok and is_gh:
            out = self._ship(task, ws, out)
        if out.ok and is_idea:
            out = self._ship_build(task, ws, out)
        return out, ws

    def _ship_build(self, task: dict, ws: Path, out: RunOutput) -> RunOutput:
        """Commit the build. With builds_owner set, push it as a PRIVATE repo; going public needs approval (L3)."""
        if self.git("status", "--porcelain", cwd=ws).strip():
            self.git("add", "-A", cwd=ws)
            self.git(*IDENT, "commit", "-q", "-m", f"perennial build: {task['title'][:60]}", cwd=ws)
        if not self.builds_owner:
            return replace(out, summary=out.summary + f"\n(build kept local: {ws})")
        self.policy.require("push_own")
        name = f"{self.builds_owner}/perennial-{slug(task['title'])}"
        url = self.gh("repo", "create", name, "--private", "--source", str(ws), "--push",
                      "--description", f"Built by perennial: {task['title'][:80]}").strip()
        return replace(out, summary=f"{out.summary}\nRepo (private): {url or name}", raw=out.raw | {"publish": name})

    def _ship(self, task: dict, ws: Path, out: RunOutput) -> RunOutput:
        if not self.git("status", "--porcelain", cwd=ws).strip():
            return replace(out, summary=out.summary + "\n(no changes to ship)")
        self.policy.require("push_own")
        self.git("add", "-A", cwd=ws)
        self.git(*IDENT, "commit", "-m", f"perennial: {task['title'][:60]}", cwd=ws)
        self.git("push", "-u", "origin", f"perennial/{task['id']}", cwd=ws)
        self.policy.require("open_pr")
        result = (ws / "RESULT.md").read_text()[:3000] if (ws / "RESULT.md").exists() else out.summary[:3000]
        url = self.gh("pr", "create", "--repo", task["source"].split(":", 1)[1], "--head", f"perennial/{task['id']}",
                      "--title", f"perennial: {task['title'][:60]}", "--body", f"Closes {task.get('url', '')}\n\n{result}").strip()
        return replace(out, summary=f"{out.summary}\nPR: {url}")
