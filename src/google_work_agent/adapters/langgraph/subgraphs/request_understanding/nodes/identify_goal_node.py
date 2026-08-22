from __future__ import annotations

from google_work_agent.application.agents.request_understanding.identify_goal import identify_goal
from google_work_agent.application.llm import StructuredLLMRuntime
from google_work_agent.ports import PromptReference

from google_work_agent.adapters.langgraph.subgraphs.request_understanding.projections.request_projection import (
    project_request_input,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingState,
)


def identify_goal_node(
    state: RequestUnderstandingState,
    *,
    llm_runtime: StructuredLLMRuntime,
    prompt_ref: PromptReference | None,
) -> RequestUnderstandingState:
    projection = project_request_input(state)
    candidate = identify_goal(
        llm_runtime=llm_runtime,
        request=projection["request"],
        prompt_ref=prompt_ref,
        confirmation_response=projection.get("confirmation_response"),
    )
    return {"ru_candidate": candidate, "ru_confirmation_response": None}
