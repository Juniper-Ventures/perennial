from perennial.ideas import IdeaSource, ideation_prompt, parse_ideas
from perennial.store import Store


def test_prompt_lists_context_and_existing_titles():
    p = ideation_prompt(charter="c", context="NOTES: build tools for founders", existing=["Old idea"], n=3)
    assert "NOTES: build tools for founders" in p and "Old idea" in p and "3" in p and '"novelty"' in p


def test_parse_array_inside_prose_clamps_and_caps():
    text = 'Here: [{"title":"A","pitch":"x","value":9,"effort":0,"novelty":3},' \
           '{"title":"B","pitch":"y","value":3,"effort":2,"novelty":2},' \
           '{"title":"C","pitch":"z","value":1,"effort":1,"novelty":1}] thanks'
    ideas = parse_ideas(text, n=2)
    assert [i["title"] for i in ideas] == ["A", "B"]
    assert (ideas[0]["value"], ideas[0]["effort"]) == (5, 1)


def test_parse_garbage_and_missing_fields():
    assert parse_ideas("no json here", n=5) == []
    assert parse_ideas('[{"title":"","pitch":"x"}, {"pitch":"no title"}]', n=5) == []


def test_idea_source_yields_only_queued(tmp_path):
    s = Store(tmp_path / "s.sqlite")
    s.add_ideas([{"title": "A", "pitch": "pa", "value": 5, "effort": 1, "novelty": 5},
                 {"title": "B", "pitch": "pb", "value": 1, "effort": 5, "novelty": 1}])
    assert IdeaSource(s).fetch() == []
    s.queue_best_idea()
    [t] = IdeaSource(s).fetch()
    assert (t.source, t.title, t.body) == ("idea:local", "A", "Build this idea end to end:\npa")
