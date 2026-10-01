from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


def task_id(source: str, ext_id: str) -> str:
    return hashlib.sha256(f"{source}\x00{ext_id}".encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Task:
    id: str
    source: str  # "<kind>:<location>", e.g. "markdown:Today.md", "github:org/repo"
    ext_id: str
    title: str
    body: str = ""
    url: str = ""

    @property
    def kind(self) -> str:
        return self.source.split(":", 1)[0]

    @classmethod
    def new(cls, source: str, ext_id: str, title: str, body: str = "", url: str = "") -> "Task":
        return cls(id=task_id(source, ext_id), source=source, ext_id=ext_id, title=title, body=body, url=url)


@dataclass(frozen=True)
class Triage:
    decision: str  # "do" | "ask" | "skip"
    value: int  # 1..5
    effort: int  # 1..5
    reason: str


@dataclass(frozen=True)
class RunOutput:
    ok: bool
    cost_usd: float
    summary: str
    raw: dict = field(default_factory=dict)
