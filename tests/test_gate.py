import json

import pytest

from perennial.gate import ALLOWED_KINDS, Outbox, relay_once
from perennial.policy import Blocked, Policy


def pol(tmp_path, autonomy=2):
    return Policy(stop_file=tmp_path / "STOP", autonomy=autonomy, daily_budget=10, run_budget=1)


def test_notify_writes_one_json_file(tmp_path):
    ob = Outbox(tmp_path / "outbox", pol(tmp_path))
    ob.notify("digest text", label="perennial-digest")
    [f] = list((tmp_path / "outbox").glob("*.json"))
    assert json.loads(f.read_text()) == {"kind": "notify", "label": "perennial-digest", "message": "digest text"}


def test_notify_blocked_at_autonomy_zero(tmp_path):
    with pytest.raises(Blocked):
        Outbox(tmp_path / "outbox", pol(tmp_path, autonomy=0)).notify("x", label="l")


def test_relay_sends_allowlisted_and_quarantines_the_rest(tmp_path):
    box = tmp_path / "outbox"
    box.mkdir()
    (box / "1.json").write_text(json.dumps({"kind": "notify", "label": "perennial-digest", "message": "hi"}))
    (box / "2.json").write_text(json.dumps({"kind": "email", "to": "x@y.z", "message": "hi"}))
    (box / "3.json").write_text("not json")
    sent = []
    n = relay_once(box, send=lambda msg, label: sent.append((msg, label)))
    assert n == 1 and sent == [("hi", "perennial-digest")]
    assert sorted(p.name for p in (box / "sent").iterdir()) == ["1.json"]
    assert sorted(p.name for p in (box / "rejected").iterdir()) == ["2.json", "3.json"]
    assert ALLOWED_KINDS == {"notify", "approve", "root_page"}


def test_relay_truncates_long_messages(tmp_path):
    box = tmp_path / "outbox"
    box.mkdir()
    (box / "1.json").write_text(json.dumps({"kind": "notify", "label": "l", "message": "x" * 10000}))
    sent = []
    relay_once(box, send=lambda m, l: sent.append(m))
    assert len(sent[0]) == 3500


def test_approval_request_routes_to_ask(tmp_path):
    from perennial.gate import Approvals

    p3 = Policy(stop_file=tmp_path / "STOP", autonomy=3, daily_budget=10, run_budget=1)
    ob = Outbox(tmp_path / "outbox", p3)
    ob.request_approval("ap1", "Make repo public?")
    asked, sent = [], []
    n = relay_once(tmp_path / "outbox", send=lambda m, l: sent.append(m), ask=lambda m, l, rid: asked.append((m, rid)))
    assert n == 1 and sent == [] and asked[0][1] == "ap1" and "Make repo public?" in asked[0][0]

    ap = Approvals(tmp_path / "approvals")
    assert ap.answer("ap1") is None
    (tmp_path / "approvals").mkdir()
    for text, want in [("Yes go", True), ("ja", True), ("godkend!", True), ("no", False),
                       ("(no reply within 900s)", False), ("maybe later", False)]:
        (tmp_path / "approvals" / "ap1.txt").write_text(text)
        assert ap.answer("ap1") is want, text


def test_approval_request_needs_autonomy_three(tmp_path):
    with pytest.raises(Blocked):
        Outbox(tmp_path / "outbox", pol(tmp_path, autonomy=2)).request_approval("x", "m")


def test_relay_without_ask_rejects_approvals(tmp_path):
    box = tmp_path / "outbox"
    box.mkdir()
    (box / "1.json").write_text(json.dumps({"kind": "approve", "id": "a", "message": "m"}))
    assert relay_once(box, send=lambda m, l: None) == 0
    assert [p.name for p in (box / "rejected").iterdir()] == ["1.json"]


def test_root_page_kind_goes_to_root_poster_only_when_enabled(tmp_path):
    ob = Outbox(tmp_path / "outbox", pol(tmp_path))
    ob.root_page("forge: built x", "# Result\nok")
    posted = []
    assert relay_once(tmp_path / "outbox", send=lambda m, l: None) == 0  # no poster -> rejected
    ob.root_page("forge: built y", "# Result\nfine")
    n = relay_once(tmp_path / "outbox", send=lambda m, l: None, post_root=lambda t, md: posted.append((t, md)))
    assert n == 1 and posted == [("forge: built y", "# Result\nfine")]


def test_root_page_needs_autonomy_two(tmp_path):
    with pytest.raises(Blocked):
        Outbox(tmp_path / "outbox", pol(tmp_path, autonomy=1)).root_page("t", "m")


def test_relay_never_resends_when_sent_dir_is_not_writable(tmp_path):
    # Live bug: sent/ belonged to another macOS user, so every 5-minute relay run sent the same digest again.
    box = tmp_path / "outbox"
    (box / "sent").mkdir(parents=True)
    (box / "1.json").write_text(json.dumps({"kind": "notify", "label": "perennial-digest", "message": "digest"}))
    (box / "sent").chmod(0o500)
    sent = []
    try:
        for _ in range(3):
            relay_once(box, send=lambda msg, label: sent.append(msg))
    finally:
        (box / "sent").chmod(0o700)
    assert sent == []


def test_relay_keeps_a_request_whose_send_failed_for_the_next_run(tmp_path):
    box = tmp_path / "outbox"
    box.mkdir()
    (box / "1.json").write_text(json.dumps({"kind": "notify", "label": "l", "message": "hi"}))

    def down(msg, label):
        raise OSError("telegram down")

    with pytest.raises(OSError):
        relay_once(box, send=down)
    sent = []
    assert relay_once(box, send=lambda msg, label: sent.append(msg)) == 1 and sent == ["hi"]
