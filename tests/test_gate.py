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
    assert ALLOWED_KINDS == {"notify"}


def test_relay_truncates_long_messages(tmp_path):
    box = tmp_path / "outbox"
    box.mkdir()
    (box / "1.json").write_text(json.dumps({"kind": "notify", "label": "l", "message": "x" * 10000}))
    sent = []
    relay_once(box, send=lambda m, l: sent.append(m))
    assert len(sent[0]) == 3500
