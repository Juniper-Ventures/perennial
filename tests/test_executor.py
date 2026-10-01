import subprocess

from perennial.executor import Executor, work_prompt
from perennial.models import RunOutput
from perennial.policy import Policy


class FakeRunner:
    def __init__(self, ok=True, touch=None):
        self.ok, self.touch, self.calls = ok, touch, []

    def run(self, prompt, cwd, model, budget_usd, timeout_s, system):
        self.calls.append((prompt, cwd, model, budget_usd))
        if self.touch:
            (cwd / self.touch).write_text("change")
        return RunOutput(ok=self.ok, cost_usd=1.25, summary="summary")


def pol(tmp_path):
    return Policy(stop_file=tmp_path / "STOP", autonomy=2, daily_budget=10, run_budget=2)


def task(kind="markdown", url=""):
    src = "markdown:Today.md" if kind == "markdown" else "github:o/r"
    return {"id": "abc123", "source": src, "ext_id": "7", "title": "Do thing", "body": "ctx", "url": url}


def test_markdown_task_runs_in_fresh_workspace(tmp_path):
    r = FakeRunner()
    ex = Executor(runner=r, policy=pol(tmp_path), workspaces=tmp_path / "ws", model="sonnet",
                  run_budget=2, timeout_s=60, charter="c", git=lambda *a, **k: None, gh=lambda *a: "")
    out, ws = ex.execute(task())
    assert out.ok and ws == tmp_path / "ws" / "abc123"
    assert r.calls[0][1] == ws and r.calls[0][3] == 2


def test_github_task_clones_branches_and_opens_pr_when_changed(tmp_path):
    git_calls, gh_calls = [], []

    def git(*args, cwd=None):
        git_calls.append(args)
        if args[:2] == ("status", "--porcelain"):
            return " M file\n"
        return ""

    def gh(*args):
        gh_calls.append(args)
        if args[:2] == ("repo", "clone"):
            (tmp_path / "ws" / "abc123").mkdir(parents=True, exist_ok=True)
        return "https://github.com/o/r/pull/9\n"

    ex = Executor(runner=FakeRunner(), policy=pol(tmp_path), workspaces=tmp_path / "ws", model="sonnet",
                  run_budget=2, timeout_s=60, charter="c", git=git, gh=gh)
    out, ws = ex.execute(task("github", url="https://github.com/o/r/issues/7"))
    assert gh_calls[0][:3] == ("repo", "clone", "o/r")
    assert ("checkout", "-b", "perennial/abc123") in git_calls
    assert any(c[:2] == ("pr", "create") for c in gh_calls)
    assert "pull/9" in out.summary


def test_prompt_demands_result_file():
    assert "RESULT.md" in work_prompt(task())


def idea_task():
    return {"id": "idea42", "source": "idea:local", "ext_id": "i1", "title": "Tiny CSV linter!", "body": "Build it", "url": ""}


def test_idea_build_inits_repo_commits_and_stays_local_without_owner(tmp_path):
    git_calls, gh_calls = [], []

    def git(*args, cwd=None):
        git_calls.append(args)
        return " M x\n" if args[:2] == ("status", "--porcelain") else ""

    ex = Executor(runner=FakeRunner(touch="README.md"), policy=pol(tmp_path), workspaces=tmp_path / "ws", model="m",
                  run_budget=2, timeout_s=60, charter="c", git=git, gh=lambda *a: gh_calls.append(a) or "")
    out, ws = ex.execute(idea_task())
    assert ("init", "-q") in git_calls
    assert any("commit" in c for c in git_calls)
    assert gh_calls == [] and "publish" not in out.raw


def test_idea_build_pushes_private_repo_and_requests_publish(tmp_path):
    gh_calls = []

    def gh(*args):
        gh_calls.append(args)
        return "https://github.com/Org/perennial-tiny-csv-linter\n"

    ex = Executor(runner=FakeRunner(touch="README.md"), policy=pol(tmp_path), workspaces=tmp_path / "ws", model="m",
                  run_budget=2, timeout_s=60, charter="c",
                  git=lambda *a, cwd=None: " M x\n" if a[:2] == ("status", "--porcelain") else "", gh=gh, builds_owner="Org")
    out, _ = ex.execute(idea_task())
    create = gh_calls[0]
    assert create[:3] == ("repo", "create", "Org/perennial-tiny-csv-linter") and "--private" in create and "--public" not in create
    assert out.raw["publish"] == "Org/perennial-tiny-csv-linter"
    assert "perennial-tiny-csv-linter" in out.summary
