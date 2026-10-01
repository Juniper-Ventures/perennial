import json
import subprocess

from perennial.runner import ClaudeRunner


def test_builds_headless_command_and_parses_json(tmp_path, monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        out = {"result": "did it", "total_cost_usd": 0.42, "is_error": False, "session_id": "s1"}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(out), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    r = ClaudeRunner(binary="claude").run("fix it", cwd=tmp_path, model="sonnet", budget_usd=3, timeout_s=60, system="be good")
    assert r.ok and r.cost_usd == 0.42 and r.summary == "did it"
    cmd = seen["cmd"]
    assert cmd[:3] == ["claude", "-p", "fix it"]
    for flag in ["--output-format", "json", "--model", "sonnet", "--max-budget-usd", "3",
                 "--permission-mode", "bypassPermissions", "--append-system-prompt", "be good"]:
        assert flag in cmd
    assert seen["kw"]["cwd"] == tmp_path and seen["kw"]["timeout"] == 60


def test_timeout_and_garbage_become_failed_runs(tmp_path, monkeypatch):
    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(subprocess, "run", boom)
    r = ClaudeRunner().run("x", cwd=tmp_path, model="m", budget_usd=1, timeout_s=1, system="")
    assert not r.ok and "timeout" in r.summary

    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="not json", stderr="err"))
    r = ClaudeRunner().run("x", cwd=tmp_path, model="m", budget_usd=1, timeout_s=1, system="")
    assert not r.ok and r.cost_usd == 0
