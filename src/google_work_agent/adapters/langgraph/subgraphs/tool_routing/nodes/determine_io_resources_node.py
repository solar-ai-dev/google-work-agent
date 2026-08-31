from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRouteStateV1
from google_work_agent.application.agents.tool_routing.determine_io_resources import (
    determine_io_resources,
)
from google_work_agent.application.agents.tool_routing.validate_route import (
    ToolRouteValidationError,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.run.guard_run_budget import (
    consume_llm_provider_calls,
)
from google_work_agent.ports.llm import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort

from ..projections.determine_io_resources_projection import (
    project_determine_io_resources_input,
)


def determine_io_resources_node(
    state: ToolRouteStateV1,
    *,
    llm_runtime: StructuredInferencePort,
    tool_catalog: SignedToolRegistry,
    prompt_ref: PromptReference | None,
) -> ToolRouteStateV1:
    projection = project_determine_io_resources_input(state)
    try:
        candidate, retry_budget = determine_io_resources(
            llm_runtime=llm_runtime,
            tool_catalog=tool_catalog,
            request_intent=projection["request_intent"],
            request=projection["request"],
            retry_budget=projection["retry_budget"],
            prompt_ref=prompt_ref,
            confirmation_response=projection["confirmation_response"],
        )
    except ToolRouteValidationError:
        return {
            "io_resource_candidate": None,
            "workflow_signal": None,
        }
    return {
        "io_resource_candidate": candidate,
        "retry_budget": consume_llm_provider_calls(retry_budget),
        "workflow_signal": None,
    }
