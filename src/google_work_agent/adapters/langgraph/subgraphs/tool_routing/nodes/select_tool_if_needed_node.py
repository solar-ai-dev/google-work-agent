from __future__ import annotations

from google_work_agent.application.agents.tool_routing.bind_registry_candidates import registry_candidates_for_route
from google_work_agent.application.agents.tool_routing.select_tool_if_needed import select_tool_if_needed
from google_work_agent.application.llm import StructuredLLMRuntime
from google_work_agent.domain import ConnectorToolCatalog
from google_work_agent.ports import PromptReference
from google_work_agent.adapters.langgraph.graph_state import request_from_state
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.projections.semantic_candidate_projection import project_semantic_candidate_input
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRoutingState


def select_tool_if_needed_node(state: ToolRoutingState, *, llm_runtime: StructuredLLMRuntime, tool_catalog: ConnectorToolCatalog, prompt_ref: PromptReference | None, revision_prompt_ref: PromptReference | None) -> ToolRoutingState:
    candidate = project_semantic_candidate_input(state)["candidate"]
    retry_budget = state.get("tr_retry_budget", state["retry_budget"])
    request = request_from_state(state)
    selected: dict[tuple[str, str], str] = {}
    for resource_type, effect_type in candidate.output_pairs:
        connector_id, eligible_tool_ids = registry_candidates_for_route(tool_catalog=tool_catalog, resource_type=resource_type, effect_type=effect_type)
        if len(eligible_tool_ids) <= 1:
            continue
        route_key = (resource_type, effect_type.value)
        tool_id, retry_budget = select_tool_if_needed(llm_runtime=llm_runtime, route_id=f"selection:{resource_type}:{effect_type.value}", connector_id=connector_id, resource_type=resource_type, effect=effect_type.value, eligible_tool_ids=eligible_tool_ids, request=request, retry_budget=retry_budget, prompt_ref=prompt_ref, revision_prompt_ref=revision_prompt_ref)
        selected[route_key] = tool_id
    return {"tr_selected_tools": selected, "tr_retry_budget": retry_budget}
