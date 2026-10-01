from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# L0 read · L1 build in sandbox · L2 ship to own space · L3 outside effects · L4 never
LEVELS = {
    "read": 0,
    "build": 1,
    "notify_owner": 1,
    "push_own": 2,
    "open_pr": 2,
    "message_human": 3,
    "publish": 3,
    "merge_main": 3,
    "write_external": 3,
    "signup": 3,
    "send_as_owner": 4,
    "spend_money": 4,
    "use_owner_credentials": 4,
}


class Blocked(PermissionError):
    pass


@dataclass(frozen=True)
class Policy:
    stop_file: Path
    autonomy: int
    daily_budget: float
    run_budget: float

    def stopped(self) -> bool:
        return Path(self.stop_file).exists()

    def can_spend(self, store) -> bool:
        return store.spent_today() + self.run_budget <= self.daily_budget

    def require(self, action: str, approved: bool = False) -> None:
        level = LEVELS[action]
        if level >= 4 or level > self.autonomy:
            raise Blocked(f"{action} (L{level}) not allowed at autonomy L{self.autonomy}")
        if level == 3 and not approved:
            raise Blocked(f"{action} (L3) needs owner approval")
