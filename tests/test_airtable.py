from perennial.airtable import records_to_markdown

RECS = [
    {"id": "r1", "fields": {"Task": "set up Juniper Foundation", "Status": "To Do", "Deadline": "2026-08-17",
                            "Next Step": "- sync w legal\n- make website", "NS Owner": {"email": "griff@x.com"}}},
    {"id": "r2", "fields": {"Task": "Dinner #1", "Status": "Done"}},
    {"id": "r3", "fields": {"Task": "write [launch] post *now*", "Status": "In Progress", "NS Owner": {"email": "esben@x.com"}}},
    {"id": "r4", "fields": {"Status": "To Do"}},
]


def test_open_records_become_checklist_items():
    md = records_to_markdown(RECS, title="TO DO")
    lines = md.splitlines()
    assert lines[0] == "# TO DO"
    assert "- [ ] set up Juniper Foundation (due 2026-08-17)" in lines
    assert "  Next: sync w legal; make website" in lines
    assert not any("Dinner" in l for l in lines)
    assert sum(l.startswith("- [ ]") for l in lines) == 2


def test_owner_filter_keeps_only_that_owner():
    md = records_to_markdown(RECS, title="TO DO", owner_email="esben@x.com")
    items = [l for l in md.splitlines() if l.startswith("- [ ]")]
    assert items == ["- [ ] write [launch] post *now*"]
