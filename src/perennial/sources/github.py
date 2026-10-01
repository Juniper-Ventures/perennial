from __future__ import annotations

import json
import subprocess
from collections.abc import Callable

from perennial.models import Task


def run_gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, timeout=60).stdout


class GitHubSource:
    def __init__(self, repo: str, label: str, gh: Callable[[list[str]], str] = run_gh):
        self.repo, self.label, self.gh = repo, label, gh
        self.source = f"github:{repo}"

    def fetch(self) -> list[Task]:
        """Raises on gh failure. The supervisor catches it and skips the sync for this source."""
        raw = self.gh(["issue", "list", "--repo", self.repo, "--label", self.label, "--state", "open",
                       "--limit", "50", "--json", "number,title,body,url"])
        return [
            Task.new(source=self.source, ext_id=str(i["number"]), title=i["title"], body=i.get("body") or "", url=i["url"])
            for i in json.loads(raw)
        ]
