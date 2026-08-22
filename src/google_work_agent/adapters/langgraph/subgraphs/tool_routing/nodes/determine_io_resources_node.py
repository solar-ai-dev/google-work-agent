from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.projections.determine_io_resources_projection import project_determine_io_resources_input
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRoutingState
from google_work_agent.application.agents.tool_routing.determine_io_resources import determine_io_resources
from google_work_agent.application.agents.tool_routing.validate_route import ToolRouteValidationError
from google_work_agent.application.llm import StructuredLLMRuntime
from google_work_agent.application.orchestration.contracts import consume_llm_provider_calls
from google_work_agent.domain import ConnectorToolCatalog
from google_work_agent.ports import PromptReference


def determine_io_resources_node(state: ToolRoutingState, *, llm_runtime: StructuredLLMRuntime, tool_catalog: ConnectorToolCatalog, prompt_ref: PromptReference | None, revision_prompt_ref: PromptReference | None) -> ToolRoutingState:
    projection = project_determine_io_resources_input(state)
    try:
        candidate, retry_budget = determine_io_resources(llm_runtime=llm_runtime, tool_catalog=tool_catalog, request_intent=projection["request_intent"], request=projection["request"], retry_budget=projection["retry_budget"], prompt_ref=prompt_ref, revision_prompt_ref=revision_prompt_ref, confirmation_response=projection["confirmation_response"])
    except ToolRouteValidationError as error:
        return {"tr_result": {"schema_version": 1, "disposition": "NEEDS_CONFIRMATION", "tool_route_plan": None, "workflow_signal": None, "reason_codes": [str(error)]}, "tr_semantic_candidate": None, "tr_confirmation_response": None}
    return {
        "tr_semantic_candidate": candidate,
        "tr_retry_budget": consume_llm_provider_calls(retry_budget),
        "tr_confirmation_response": None,
        "tr_result": None,
    }
