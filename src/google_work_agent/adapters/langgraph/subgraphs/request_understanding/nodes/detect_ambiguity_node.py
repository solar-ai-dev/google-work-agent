from __future__ import annotations

from google_work_agent.adapters.langgraph.agent_kernel import (
    consume_llm_call_budget,
    ensure_llm_call_budget,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.projections.detect_ambiguity_projection import (  # noqa: E501
    project_detect_ambiguity_input,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingStateV2,
)
from google_work_agent.application.agents.request_understanding.detect_ambiguity import (
    detect_ambiguity,
)
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.ports.llm import PromptReference


def detect_ambiguity_node(
    state: RequestUnderstandingStateV2,
    *,
    llm_runtime: StructuredLLMRuntime,
    prompt_ref: PromptReference | None,
) -> RequestUnderstandingStateV2:
    projection = project_detect_ambiguity_input(state)
    ensure_llm_call_budget(state)
    return {
        "ambiguity_candidate": detect_ambiguity(
            llm_runtime=llm_runtime,
            request=projection["request"],
            goal_candidate=projection["goal_candidate"],
            prompt_ref=prompt_ref,
            confirmation_response=projection.get("confirmation_response"),
        ),
        "retry_budget": consume_llm_call_budget(state),
    }
