"""Canonical retention purge orchestration."""

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.application.use_cases.trace_event.observability import emit_audit_event
from google_work_agent.ports.events.observability_events import (
    EventCategory,
    ObservabilityContext,
    Severity,
)
from google_work_agent.ports.persistence.retention_repository import (
    RetentionCutoffs,
    RetentionPurgeResult,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.settings_port import SettingsPort

_DAY_MS = 86_400_000
_AUDIT_RETENTION_DAYS = 90
_MAX_BATCH_LIMIT = 500


@dataclass(frozen=True, slots=True)
class PurgeRetentionCommand:
    now_ms: int
    batch_limit: int = _MAX_BATCH_LIMIT


class PurgeRetentionHandler:
    def __init__(
        self,
        *,
        settings: SettingsPort,
        unit_of_work_factory: Callable[[], UnitOfWork],
    ) -> None:
        self._settings = settings
        self._unit_of_work_factory = unit_of_work_factory

    def handle(self, command: PurgeRetentionCommand) -> RetentionPurgeResult:
        retention_days = self._settings.get().run_retention_days
        if not 1 <= retention_days <= 30:
            raise ValueError("retention_days must be between 1 and 30")
        if not 1 <= command.batch_limit <= _MAX_BATCH_LIMIT:
            raise ValueError("batch_limit must be between 1 and 500")
        cutoff = command.now_ms - retention_days * _DAY_MS
        cutoffs = RetentionCutoffs(
            terminal_run_ms=cutoff,
            message_ms=cutoff,
            conversation_ms=cutoff,
            trace_ms=cutoff,
            audit_ms=command.now_ms - _AUDIT_RETENTION_DAYS * _DAY_MS,
        )
        with self._unit_of_work_factory() as unit_of_work:
            result = unit_of_work.retention.purge_batch(cutoffs, command.batch_limit)
            emit_audit_event(
                unit_of_work,
                correlation=ObservabilityContext(),
                account_id=None,
                actor_type="SYSTEM",
                actor_id="purge_retention",
                actor_display="PurgeRetentionHandler",
                event_name="PURGE_COMPLETED",
                event_category=EventCategory.PERSISTENCE,
                occurred_at_ms=command.now_ms,
                severity=Severity.INFO,
                component="retention",
                environment="local",
                release_version="dev",
                attributes={
                    "runs": result.runs,
                    "checkpoints": result.checkpoints,
                    "receipts": result.receipts,
                    "messages": result.messages,
                    "conversations": result.conversations,
                    "traces": result.traces,
                    "audits": result.audits,
                    "batch_limit": command.batch_limit,
                },
                result_code="TRANSITION_APPLIED",
                status="COMPLETED",
                required=True,
            )
            unit_of_work.commit()
        return result
