"""Typed owner results accepted by the deterministic Main Supervisor."""

from __future__ import annotations

from typing import Literal, TypedDict

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    RetrievalResultV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkAnalysisResultV2,
)
from google_work_agent.ports.system.contracts.workflow_signal import (
    RetrievalRequiredV1,
    RouteReconsiderationRequiredV1,
)


class RetrievalRouteResultV1(TypedDict):
    """Retrieval disposition and its already-materialized canonical artifact."""

    disposition: str
    typed_result: RetrievalResultV1 | None


class WorkAnalysisRouteResultV1(TypedDict):
    """Owner-local Work Analysis result consumed only by the Supervisor."""

    disposition: Literal[
        "COMPLETE",
        "NEEDS_MORE_DATA",
        "ROUTE_RECONSIDERATION_REQUIRED",
        "BLOCKED",
    ]
    typed_result: WorkAnalysisResultV2 | None
    workflow_signal: RetrievalRequiredV1 | RouteReconsiderationRequiredV1 | None
    reason_codes: list[str]


class PlanningRouteResultV1(TypedDict):
    """Owner-local Planning result consumed only by the Supervisor."""

    disposition: Literal["ANSWER_ONLY", "PLAN_READY", "BLOCKED"]
    typed_result: object | None
    reason_codes: list[str]


__all__ = [
    "PlanningRouteResultV1",
    "RetrievalRouteResultV1",
    "WorkAnalysisRouteResultV1",
]
