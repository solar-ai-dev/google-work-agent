"""Narrow connector read capability used by acquisition workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from google_work_agent.application.workflows.handoff_contracts import SourceFetchPlanV1
from google_work_agent.ports import ResourceSnapshot, SelectedResourceRef


@dataclass(frozen=True, slots=True)
class ConnectorReadRequest:
    """One already-planned connector read invocation."""

    plan: SourceFetchPlanV1
    selected_resources: tuple[SelectedResourceRef, ...]
    prefer_selected_resources: bool
    remaining_budget: dict[str, int]
    now_ms: int
    timezone: str


@dataclass(frozen=True, slots=True)
class ConnectorReadResult:
    """Normalized resources and an optional deterministic read disposition."""

    snapshots: tuple[ResourceSnapshot, ...]
    error_code: str | None = None


class ConnectorReadPort(Protocol):
    """Execute one acquisition plan without exposing provider gateway methods."""

    def read(self, request: ConnectorReadRequest) -> ConnectorReadResult:
        """Return resources in the acquisition workflow's normalized shape."""
