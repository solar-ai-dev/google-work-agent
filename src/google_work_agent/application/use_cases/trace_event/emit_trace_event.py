"""Append one sanitized canonical TraceEvent in a short UoW."""

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.application.use_cases.trace_event.observability import emit_trace_event
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.observability import (
    EventCategory,
    ObservabilityContext,
    Severity,
)


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
            emit_trace_event(
                unit_of_work,
                correlation=command.correlation,
                event_name=command.event_name,
                event_category=command.event_category,
                occurred_at_ms=command.occurred_at_ms,
                severity=command.severity,
                component=command.component,
                environment=self._environment,
                release_version=self._release_version,
                attributes=command.attributes,
                result_code=command.result_code,
                status=command.status,
                duration_ms=command.duration_ms,
                required=command.required,
            )
            unit_of_work.commit()
        return EmitTraceEventResult(appended=True)

    def record(
        self,
        *,
        event_name: str,
        severity: Severity,
        correlation: ObservabilityContext,
        attributes: dict[str, object],
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
                attributes=attributes,
                result_code=result_code,
                status=status,
                duration_ms=duration_ms,
            )
        )


__all__ = ["EmitTraceEventCommand", "EmitTraceEventHandler", "EmitTraceEventResult"]
