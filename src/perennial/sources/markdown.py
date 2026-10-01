from __future__ import annotations

import re
from pathlib import Path

from perennial.models import Task

ITEM = re.compile(r"^\s*- \[ \] (.+?)\s*$")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$")
EMPHASIS = re.compile(r"(\*\*|__|`)")


class MarkdownSource:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.source = f"markdown:{self.path.name}"

    def fetch(self) -> list[Task]:
        if not self.path.exists():
            return []
        section = ""
        out = []
        for line in self.path.read_text().splitlines():
            if h := HEADING.match(line):
                section = h.group(1)
                continue
            if m := ITEM.match(line):
                title = EMPHASIS.sub("", m.group(1)).strip()[:300]
                body = f"Section: {section}\n{title}" if section else title
                out.append(Task.new(source=self.source, ext_id=title, title=title, body=body))
        return out
