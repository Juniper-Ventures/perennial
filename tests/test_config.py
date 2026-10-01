import pytest

from perennial.config import ConfigError, load_config

GOOD = """
[perennial]
name = "ember"
charter = "You maintain the owner's side projects."
autonomy = 2
daily_budget_usd = 20
run_budget_usd = 3
run_timeout_s = 3600
triage_model = "haiku"
work_model = "sonnet"
digest_hour = 18
home = "{home}"

[[sources]]
type = "markdown"
path = "{home}/inbox/Today.md"

[[sources]]
type = "github"
repos = ["perennial-bot/sandbox"]
label = "perennial"
"""


def test_load_good_config(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(GOOD.format(home=tmp_path))
    c = load_config(p)
    assert c.name == "ember"
    assert c.autonomy == 2
    assert c.store_path == tmp_path / "store.sqlite"
    assert c.workspaces == tmp_path / "workspaces"
    assert c.outbox == tmp_path / "outbox"
    assert c.stop_file == tmp_path / "STOP"
    assert [s["type"] for s in c.sources] == ["markdown", "github"]


def test_autonomy_above_three_is_rejected(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(GOOD.format(home=tmp_path).replace("autonomy = 2", "autonomy = 9"))
    with pytest.raises(ConfigError, match="autonomy"):
        load_config(p)


def test_unknown_source_type_is_rejected(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(GOOD.format(home=tmp_path).replace('type = "github"', 'type = "gmail"'))
    with pytest.raises(ConfigError, match="gmail"):
        load_config(p)


def test_outbox_can_point_at_shared_dir(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(GOOD.format(home=tmp_path).replace('digest_hour = 18', 'digest_hour = 18\noutbox = "/Users/Shared/perennial/outbox"'))
    assert str(load_config(p).outbox) == "/Users/Shared/perennial/outbox"


def test_phase2_defaults_and_autonomy_three(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(GOOD.format(home=tmp_path).replace("autonomy = 2", "autonomy = 3"))
    c = load_config(p)
    assert c.autonomy == 3
    assert (c.idea_hour, c.ideas_per_day, c.idea_context, c.builds_owner) == (3, 5, [], "")
    assert c.approvals == tmp_path / "approvals"


def test_autonomy_four_is_rejected(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(GOOD.format(home=tmp_path).replace("autonomy = 2", "autonomy = 4"))
    with pytest.raises(ConfigError, match="autonomy"):
        load_config(p)


def test_phase2_overrides(tmp_path):
    p = tmp_path / "config.toml"
    extra = 'digest_hour = 18\nidea_hour = 2\nideas_per_day = 3\nbuilds_owner = "Org"\napprovals = "/Users/Shared/perennial/inbox/approvals"\nidea_context = ["/a.md"]'
    p.write_text(GOOD.format(home=tmp_path).replace("digest_hour = 18", extra))
    c = load_config(p)
    assert (c.idea_hour, c.ideas_per_day, c.builds_owner, c.idea_context) == (2, 3, "Org", ["/a.md"])
    assert str(c.approvals) == "/Users/Shared/perennial/inbox/approvals"
