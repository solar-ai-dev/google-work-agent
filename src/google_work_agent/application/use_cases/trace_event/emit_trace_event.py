"""Append one sanitized canonical TraceEvent in a short UoW."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.observability import (
    EventCategory,
    EventValidationError,
    ObservabilityContext,
    ObservabilityError,
    Severity,
    create_event_envelope,
    serialize_event_envelope,
)


class TraceWriteError(ObservabilityError):
    """Raised when a required diagnostic Trace append fails."""


@dataclass(frozen=True, slots=True)
class EmitTraceEventCommand:
    correlation: ObservabilityContext
    event_name: str
    event_category: EventCategory
    occurred_at_ms: int
    severity: Severity
    component: str
    attributes: dict[str, object]
    result_code: str | None = None
    status: str | None = None
    duration_ms: int | None = None
    required: bool = False


@dataclass(frozen=True, slots=True)
class EmitTraceEventResult:
    appended: bool


class EmitTraceEventHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        environment: str,
        release_version: str,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._environment = environment
        self._release_version = release_version
        self._now_ms = now_ms

    def __call__(self, command: EmitTraceEventCommand) -> EmitTraceEventResult:
        with self._unit_of_work_factory() as unit_of_work:
            if command.correlation.run_id is None:
                raise EventValidationError("trace events require run_id")
            envelope = create_event_envelope(
                event_name=command.event_name,
                event_category=command.event_category,
                occurred_at_ms=command.occurred_at_ms,
                severity=command.severity,
                component=command.component,
                environment=self._environment,
                release_version=self._release_version,
                correlation=command.correlation,
                attributes=command.attributes,
                result_code=command.result_code,
                status=command.status,
                duration_ms=command.duration_ms,
            )
            try:
                unit_of_work.traces.append(
                    TraceEventRecord(
                        run_id=command.correlation.run_id,
                        action_id=command.correlation.action_id,
                        event_type=command.event_name,
                        status=command.status,
                        duration_ms=command.duration_ms,
                        payload_json=serialize_event_envelope(envelope),
                        created_at_ms=command.occurred_at_ms,
                    )
                )
            except Exception as error:
                if command.required:
                    raise TraceWriteError("trace append failed") from error
                return EmitTraceEventResult(appended=False)
            unit_of_work.commit()
        return EmitTraceEventResult(appended=True)

    def record(
        self,
        *,
        event_name: str,
        severity: Severity,
        correlation: ObservabilityContext,
        attributes: Mapping[str, object],
        result_code: str | None = None,
        status: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """LLM runtime recorder surface delegated to the exact command owner."""
        if self._now_ms is None or correlation.run_id is None:
            return
        self(
            EmitTraceEventCommand(
                correlation=correlation,
                event_name=event_name,
                event_category=EventCategory.LLM,
                occurred_at_ms=self._now_ms(),
                severity=severity,
                component="llm-runtime",
                attributes=dict(attributes),
                result_code=result_code,
                status=status,
                duration_ms=duration_ms,
            )
        )


__all__ = [
    "EmitTraceEventCommand",
    "EmitTraceEventHandler",
    "EmitTraceEventResult",
    "TraceWriteError",
]
