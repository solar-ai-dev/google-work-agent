"""Validate and prepare a restore plan through Application authority."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class CreateRestorePlanCommand:
    backup_id: str


@dataclass(frozen=True, slots=True)
class CreateRestorePlanResult:
    plan: dict[str, object]


class CreateRestorePlanHandler:
    def __init__(self, *, service_factory: Callable[[], Any | None]) -> None:
        self._service_factory = service_factory

    def handle(self, command: CreateRestorePlanCommand) -> CreateRestorePlanResult:
        service = self._service_factory()
        if service is None:
            raise RuntimeError("RESTORE_UNAVAILABLE")
        plan = service(command.backup_id)
        return CreateRestorePlanResult(
            plan={
                "backup": asdict(plan.backup),
                "backup_path": str(plan.backup_path),
                "current_db_backup_required": plan.current_db_backup_required,
                "downgrade_blocked": plan.downgrade_blocked,
            }
        )
