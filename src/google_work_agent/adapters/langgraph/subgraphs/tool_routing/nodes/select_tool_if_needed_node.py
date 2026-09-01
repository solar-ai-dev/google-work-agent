from __future__ import annotations

from typing import cast

from google_work_agent.adapters.langgraph.main.state import request_from_state
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1
from google_work_agent.application.agents.tool_routing.contracts.route_binding_candidate import (
    BoundOutputRouteCandidateV1,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    OutputToolRouteV1,
)
from google_work_agent.application.agents.tool_routing.select_tool_if_needed import (
    select_tool_if_needed,
)
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
)

from ..projections.select_tool_if_needed_projection import (
    project_select_tool_if_needed_input,
)


def select_tool_if_needed_node(
    state: ToolRouteStateV1,
    *,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference | None,
) -> ToolRouteStateV1:
    projection = project_select_tool_if_needed_input(state)
    candidates = cast(list[BoundOutputRouteCandidateV1], projection["registry_candidates"])
    confirmation_response = cast(
        ConfirmationResponseProjectionV1 | None,
        projection["confirmation_response"],
    )
    retry_budget = state["retry_budget"]
    request = request_from_state(state)
    selected: list[OutputToolRouteV1] = []
    for bound in candidates:
        if len(bound.eligible_tool_ids) == 1:
            tool_id = bound.eligible_tool_ids[0]
            reason_code = "REGISTRY_SINGLE_CANDIDATE"
        else:
            tool_id, retry_budget = select_tool_if_needed(
                llm_runtime=llm_runtime,
                route_id=bound.route_id,
                connector_id=bound.connector_id,
                resource_type=bound.resource_type,
                effect=bound.effect,
                eligible_tool_ids=bound.eligible_tool_ids,
                request=request,
                retry_budget=retry_budget,
                prompt_ref=prompt_ref,
                confirmation_response=confirmation_response,
            )
            reason_code = "LLM_SELECTED_FROM_BOUND_REGISTRY_CANDIDATES"
        selected.append(
            {
                "route_id": bound.route_id,
                "resource_type": bound.resource_type,
                "connector_id": bound.connector_id,
                "effect": bound.effect,
                "selected_tool_id": tool_id,
                "reason_codes": [reason_code],
            }
        )
    return {"bound_output_routes": selected, "retry_budget": retry_budget}
