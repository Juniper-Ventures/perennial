from perennial.sources.markdown import MarkdownSource

DOC = """# 2026-10-01
### Plan
- [ ] **Send the invoice** · today
- [x] Already done
  - [ ] Nested sub-item
Some text - [ ] not a checklist
### Ideas
- [ ] Build a CLI for the blog
"""


def test_reads_open_checklist_items_with_heading_context(tmp_path):
    p = tmp_path / "Today.md"
    p.write_text(DOC)
    tasks = MarkdownSource(p).fetch()
    titles = [t.title for t in tasks]
    assert titles == ["Send the invoice · today", "Nested sub-item", "Build a CLI for the blog"]
    assert tasks[2].body == "Section: Ideas\nBuild a CLI for the blog"
    assert tasks[0].source == "markdown:Today.md"


def test_missing_file_yields_nothing(tmp_path):
    assert MarkdownSource(tmp_path / "nope.md").fetch() == []
