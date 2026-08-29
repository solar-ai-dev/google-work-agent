from __future__ import annotations

from typing import TypedDict, cast

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ScopeExpansionRequiredV1,
    ToolRoutePlanV2,
)


class ValidateRouteInput(TypedDict):
    final_route: ToolRoutePlanV2 | None
    workflow_signal: ScopeExpansionRequiredV1 | None


def project_validate_route_input(state: ToolRouteStateV1) -> ValidateRouteInput:
    return {
        "final_route": state.get("final_route"),
        "workflow_signal": cast(ScopeExpansionRequiredV1 | None, state.get("workflow_signal")),
    }
