from __future__ import annotations

from google_work_agent.adapters.langgraph.agent_kernel import (
    consume_llm_call_budget,
    ensure_llm_call_budget,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingStateV2,
)
from google_work_agent.application.agents.request_understanding.identify_goal import identify_goal
from google_work_agent.ports.llm import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort

from ..projections.identify_goal_projection import (
    project_identify_goal_input,
)


def identify_goal_node(
    state: RequestUnderstandingStateV2,
    *,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference | None,
) -> RequestUnderstandingStateV2:
    projection = project_identify_goal_input(state)
    ensure_llm_call_budget(state)
    candidate = identify_goal(
        llm_runtime=llm_runtime,
        request=projection["request"],
        prompt_ref=prompt_ref,
        confirmation_response=projection.get("confirmation_response"),
    )
    return {
        "goal_candidate": candidate,
        "retry_budget": consume_llm_call_budget(state),
    }
