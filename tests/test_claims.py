from perennial.claims import Claims


def test_first_claim_wins_across_instances(tmp_path):
    a, b = Claims(tmp_path / "c.sqlite"), Claims(tmp_path / "c.sqlite")
    assert a.claim("t1", "ember")
    assert not b.claim("t1", "sage")
    assert a.claim("t1", "ember")  # re-claim by the owner is fine
    assert b.owner_of("t1") == "ember"


def test_release_only_by_owner(tmp_path):
    c = Claims(tmp_path / "c.sqlite")
    c.claim("t1", "ember")
    c.release("t1", "sage")
    assert c.owner_of("t1") == "ember"
    c.release("t1", "ember")
    assert c.owner_of("t1") is None
    assert c.claim("t1", "sage")
