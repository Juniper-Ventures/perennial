import json

from perennial.root import html_items, items_to_markdown

PAGE = """<html><body><h1>Inbox</h1><p>Put one todo per bullet.</p>
<ul><li>Build a CSV dedupe CLI</li><li><s>Old thing</s></li><li>✅ done already</li>
<li>Research <b>EU AI Act</b> deadlines &amp; summarize</li><li>[x] checked</li><li>   </li></ul>
<ol><li>Draft the Q4 LP update outline</li></ol></body></html>"""


def test_open_list_items_only():
    assert html_items(PAGE) == ["Build a CSV dedupe CLI", "Research EU AI Act deadlines & summarize",
                                "Draft the Q4 LP update outline"]


def test_markdown_output():
    md = items_to_markdown(["A", "B"], title="Perennial inbox")
    assert md == "# Perennial inbox\n- [ ] A\n- [ ] B\n"
