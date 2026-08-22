"""Narrow connector read capability used by acquisition workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from google_work_agent.application.orchestration.handoff_contracts import SourceFetchPlanV1
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
    allowed_read_tool_ids: frozenset[str] | None = None
    # This value is only injected by Retrieval's deterministic local read
    # node after resolving a run-scoped cache handle.  It must never be put in
    # graph state or a prompt.
    page_token: str | None = None


@dataclass(frozen=True, slots=True)
class ConnectorReadResult:
    """Normalized resources and an optional deterministic read disposition."""

    snapshots: tuple[ResourceSnapshot, ...]
    error_code: str | None = None
    # Raw provider continuation.  The caller must immediately place it in the
    # run-scoped Retrieval read cache and retain only that cache handle.
    next_page_token: str | None = None


class ConnectorReadPort(Protocol):
    """Execute one acquisition plan without exposing provider gateway methods."""

    def read(self, request: ConnectorReadRequest) -> ConnectorReadResult:
        """Return resources in the acquisition workflow's normalized shape."""
