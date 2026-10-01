from __future__ import annotations

from pathlib import Path

from perennial.sources.github import GitHubSource
from perennial.sources.markdown import MarkdownSource


def load_sources(cfg) -> list:
    out = []
    for s in cfg.sources:
        if s["type"] == "markdown":
            out.append(MarkdownSource(Path(s["path"])))
        elif s["type"] == "github":
            out.extend(GitHubSource(repo=r, label=s.get("label", "perennial")) for r in s["repos"])
    return out
