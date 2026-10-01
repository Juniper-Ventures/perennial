from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

SOURCE_TYPES = {"markdown", "github"}
MAX_AUTONOMY = 3  # L3 (outside effects) always needs owner approval; L4 is never allowed


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    name: str
    charter: str
    autonomy: int
    daily_budget_usd: float
    run_budget_usd: float
    run_timeout_s: int
    triage_model: str
    work_model: str
    digest_hour: int
    home: Path
    sources: list[dict]
    outbox_override: Path | None = None
    approvals_override: Path | None = None
    idea_hour: int = 3
    ideas_per_day: int = 5
    idea_context: list = None  # type: ignore[assignment]
    builds_owner: str = ""
    claims: Path | None = None
    post_results_to_root: bool = False

    @property
    def store_path(self) -> Path:
        return self.home / "store.sqlite"

    @property
    def workspaces(self) -> Path:
        return self.home / "workspaces"

    @property
    def outbox(self) -> Path:
        return self.outbox_override or self.home / "outbox"

    @property
    def approvals(self) -> Path:
        return self.approvals_override or self.home / "approvals"

    @property
    def stop_file(self) -> Path:
        return self.home / "STOP"


def load_config(path: Path) -> Config:
    data = tomllib.loads(Path(path).read_text())
    p = data.get("perennial") or {}
    try:
        cfg = Config(
            name=str(p["name"]),
            charter=str(p["charter"]),
            autonomy=int(p["autonomy"]),
            daily_budget_usd=float(p["daily_budget_usd"]),
            run_budget_usd=float(p["run_budget_usd"]),
            run_timeout_s=int(p["run_timeout_s"]),
            triage_model=str(p["triage_model"]),
            work_model=str(p["work_model"]),
            digest_hour=int(p["digest_hour"]),
            home=Path(p["home"]).expanduser(),
            sources=list(data.get("sources") or []),
            outbox_override=Path(p["outbox"]).expanduser() if p.get("outbox") else None,
            approvals_override=Path(p["approvals"]).expanduser() if p.get("approvals") else None,
            idea_hour=int(p.get("idea_hour", 3)),
            ideas_per_day=int(p.get("ideas_per_day", 5)),
            idea_context=list(p.get("idea_context", [])),
            builds_owner=str(p.get("builds_owner", "")),
            claims=Path(p["claims"]).expanduser() if p.get("claims") else None,
            post_results_to_root=bool(p.get("post_results_to_root", False)),
        )
    except KeyError as e:
        raise ConfigError(f"missing [perennial] key: {e.args[0]}") from None
    if not 0 <= cfg.autonomy <= MAX_AUTONOMY:
        raise ConfigError(f"autonomy must be 0..{MAX_AUTONOMY}, got {cfg.autonomy}")
    if cfg.run_budget_usd > cfg.daily_budget_usd:
        raise ConfigError("run_budget_usd cannot exceed daily_budget_usd")
    for s in cfg.sources:
        if s.get("type") not in SOURCE_TYPES:
            raise ConfigError(f"unknown source type: {s.get('type')}")
    return cfg
