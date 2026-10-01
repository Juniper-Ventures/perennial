from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

SOURCE_TYPES = {"markdown", "github"}
MAX_AUTONOMY_PHASE_1 = 2  # L3 (outside effects) needs the approval gate from phase 2


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
        )
    except KeyError as e:
        raise ConfigError(f"missing [perennial] key: {e.args[0]}") from None
    if not 0 <= cfg.autonomy <= MAX_AUTONOMY_PHASE_1:
        raise ConfigError(f"autonomy must be 0..{MAX_AUTONOMY_PHASE_1} in phase 1, got {cfg.autonomy}")
    if cfg.run_budget_usd > cfg.daily_budget_usd:
        raise ConfigError("run_budget_usd cannot exceed daily_budget_usd")
    for s in cfg.sources:
        if s.get("type") not in SOURCE_TYPES:
            raise ConfigError(f"unknown source type: {s.get('type')}")
    return cfg
