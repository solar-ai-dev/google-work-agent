from __future__ import annotations

from google_work_agent.adapters.langgraph.main.state import request_from_state
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.projections.selection_projection import (
    project_selection_input,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRoutingState
from google_work_agent.application.agents.tool_routing.select_tool_if_needed import (
    select_tool_if_needed,
)
from google_work_agent.application.orchestration.contracts import consume_llm_provider_calls
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.ports.llm import PromptReference


def select_tool_if_needed_node(
    state: ToolRoutingState,
    *,
    llm_runtime: StructuredLLMRuntime,
    prompt_ref: PromptReference | None,
    revision_prompt_ref: PromptReference | None,
) -> ToolRoutingState:
    binding = project_selection_input(state)["binding"]
    retry_budget = state.get("tr_retry_budget", state["retry_budget"])
    request = request_from_state(state)
    selected: dict[tuple[str, str], str] = {}
    for bound in binding.output_candidates:
        if len(bound.eligible_tool_ids) == 1:
            selected[(bound.resource_type, bound.effect)] = bound.eligible_tool_ids[0]
            continue
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
            revision_prompt_ref=revision_prompt_ref,
        )
        retry_budget = consume_llm_provider_calls(retry_budget)
        selected[(bound.resource_type, bound.effect)] = tool_id
    return {"tr_selected_tools": selected, "tr_retry_budget": retry_budget}
