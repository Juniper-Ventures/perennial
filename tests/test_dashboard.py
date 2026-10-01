from perennial.config import load_config
from perennial.dashboard import render
from perennial.models import Task, Triage
from perennial.store import Store


def cfg(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(f"""
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
    return load_config(p)


def test_render_shows_state_and_escapes_task_text(tmp_path):
    c = cfg(tmp_path)
    s = Store(c.store_path)
    s.sync("markdown:Today.md", [Task.new(source="markdown:Today.md", ext_id="x", title="<b>bold</b> & co")])
    tid = s.tasks()[0]["id"]
    s.set_triage(tid, Triage("do", 4, 2, "fine"))
    s.add_ideas([{"title": "Linter", "pitch": "lint csv", "value": 5, "effort": 1, "novelty": 4}])
    page = render(s, c)
    assert "ember" in page and "running" in page and "Linter" in page
    assert "&lt;b&gt;bold&lt;/b&gt; &amp; co" in page and "<b>bold</b>" not in page
    (tmp_path / "STOP").write_text("")
    assert "STOPPED" in render(s, c)
