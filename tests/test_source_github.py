import json

import pytest

from perennial.sources.github import GitHubSource


def test_maps_gh_issue_json_to_tasks():
    calls = []

    def fake_gh(args):
        calls.append(args)
        return json.dumps([{"number": 7, "title": "Add CI", "body": "use uv", "url": "https://github.com/o/r/issues/7"}])

    src = GitHubSource(repo="o/r", label="perennial", gh=fake_gh)
    [t] = src.fetch()
    assert (t.source, t.ext_id, t.title, t.url) == ("github:o/r", "7", "Add CI", "https://github.com/o/r/issues/7")
    assert t.body == "use uv"
    assert calls == [["issue", "list", "--repo", "o/r", "--label", "perennial", "--state", "open",
                      "--limit", "50", "--json", "number,title,body,url"]]


def test_gh_failure_raises_so_supervisor_skips_sync():
    # If fetch returned [] on error, Store.sync would mark every open task of the repo 'gone'.
    def broken(args):
        raise RuntimeError("gh exploded")

    with pytest.raises(RuntimeError):
        GitHubSource(repo="o/r", label="x", gh=broken).fetch()
