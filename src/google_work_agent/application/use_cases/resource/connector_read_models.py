"""Application-owned materialization values for planned Connector reads."""

from dataclasses import dataclass

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    SourceFetchPlanV1,
)
from google_work_agent.ports.connector.contracts.google_workspace import ResourceSnapshot
from google_work_agent.ports.system.contracts.workflow_execution import SelectedResourceRef


@dataclass(frozen=True, slots=True)
class PlannedConnectorRead:
    plan: SourceFetchPlanV1
    selected_resources: tuple[SelectedResourceRef, ...]
    prefer_selected_resources: bool
    remaining_budget: dict[str, int]
    now_ms: int
    timezone: str
    allowed_read_tool_ids: frozenset[str] | None = None
    page_token: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedConnectorRead:
    snapshots: tuple[ResourceSnapshot, ...]
    error_code: str | None = None
    next_page_token: str | None = None


__all__ = ["NormalizedConnectorRead", "PlannedConnectorRead"]
