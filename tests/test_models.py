from perennial.models import Task, task_id


def test_task_id_is_stable_and_source_scoped():
    a = task_id("markdown:Today.md", "fix the invoice script")
    b = task_id("markdown:Today.md", "fix the invoice script")
    c = task_id("github:org/repo", "fix the invoice script")
    assert a == b
    assert a != c
    assert len(a) == 16


def test_task_builds_its_id():
    t = Task.new(source="github:org/repo", ext_id="12", title="Add CI", body="", url="https://x/12")
    assert t.id == task_id("github:org/repo", "12")
    assert t.kind == "github"
