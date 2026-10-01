from perennial.models import RunOutput, Task
from perennial.triage import parse_triage, triage_prompt, triage


def test_prompt_contains_task_and_rules():
    t = Task.new(source="markdown:Today.md", ext_id="x", title="Book flights", body="Section: Plan\nBook flights")
    p = triage_prompt(t, charter="You build software.")
    assert "Book flights" in p and '"decision"' in p and "spend money" in p


def test_parse_accepts_json_inside_prose():
    tr = parse_triage('Sure. {"decision":"do","value":4,"effort":2,"reason":"small script"} done')
    assert (tr.decision, tr.value, tr.effort) == ("do", 4, 2)


def test_parse_failure_defaults_to_ask():
    tr = parse_triage("I am not sure")
    assert tr.decision == "ask"


def test_out_of_range_scores_are_clamped():
    tr = parse_triage('{"decision":"do","value":9,"effort":0,"reason":""}')
    assert (tr.value, tr.effort) == (5, 1)


class FakeRunner:
    def __init__(self, text):
        self.text = text

    def run(self, prompt, cwd, model, budget_usd, timeout_s, system):
        return RunOutput(ok=True, cost_usd=0.01, summary=self.text)


def test_triage_uses_cheap_budget(tmp_path):
    t = Task.new(source="s:x", ext_id="1", title="t")
    tr, cost = triage(t, FakeRunner('{"decision":"skip","value":1,"effort":1,"reason":"personal errand"}'),
                      cwd=tmp_path, model="haiku", charter="c")
    assert tr.decision == "skip" and cost == 0.01
