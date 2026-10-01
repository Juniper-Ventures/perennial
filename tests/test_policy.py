import pytest

from perennial.policy import LEVELS, Blocked, Policy


class FakeStore:
    def __init__(self, spent):
        self._spent = spent

    def spent_today(self):
        return self._spent


def test_kill_switch(tmp_path):
    p = Policy(stop_file=tmp_path / "STOP", autonomy=2, daily_budget=10, run_budget=2)
    assert not p.stopped()
    (tmp_path / "STOP").write_text("")
    assert p.stopped()


def test_budget_needs_room_for_a_full_run(tmp_path):
    p = Policy(stop_file=tmp_path / "STOP", autonomy=2, daily_budget=10, run_budget=2)
    assert p.can_spend(FakeStore(7.9))
    assert not p.can_spend(FakeStore(8.1))


@pytest.mark.parametrize("action,allowed", [
    ("read", True), ("build", True), ("push_own", True), ("open_pr", True),
    ("notify_owner", True), ("message_human", False), ("publish", False), ("merge_main", False),
    ("send_as_owner", False), ("spend_money", False),
])
def test_autonomy_two_allows_build_and_pr_but_not_outside_effects(tmp_path, action, allowed):
    p = Policy(stop_file=tmp_path / "STOP", autonomy=2, daily_budget=10, run_budget=2)
    if allowed:
        p.require(action)
    else:
        with pytest.raises(Blocked):
            p.require(action)


def test_level_four_actions_are_never_allowed():
    assert LEVELS["send_as_owner"] == 4 and LEVELS["spend_money"] == 4


def test_l3_needs_autonomy_three_and_approval(tmp_path):
    p3 = Policy(stop_file=tmp_path / "STOP", autonomy=3, daily_budget=10, run_budget=2)
    p2 = Policy(stop_file=tmp_path / "STOP", autonomy=2, daily_budget=10, run_budget=2)
    with pytest.raises(Blocked):
        p3.require("publish")
    p3.require("publish", approved=True)
    with pytest.raises(Blocked):
        p2.require("publish", approved=True)
    with pytest.raises(Blocked):
        p3.require("spend_money", approved=True)
