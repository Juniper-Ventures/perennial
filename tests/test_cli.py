from perennial.cli import main


def test_stop_and_start_toggle_kill_switch(tmp_path, capsys):
    cfg = tmp_path / "config.toml"
    cfg.write_text(f"""
[perennial]
name = "ember"
charter = "c"
autonomy = 2
daily_budget_usd = 5
run_budget_usd = 1
run_timeout_s = 60
triage_model = "haiku"
work_model = "sonnet"
digest_hour = 18
home = "{tmp_path}"
""")
    assert main(["--config", str(cfg), "stop"]) == 0
    assert (tmp_path / "STOP").exists()
    assert main(["--config", str(cfg), "status"]) == 0
    assert "STOPPED" in capsys.readouterr().out
    assert main(["--config", str(cfg), "start"]) == 0
    assert not (tmp_path / "STOP").exists()
