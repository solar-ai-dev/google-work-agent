from __future__ import annotations

from google_work_agent.application.agents.retrieval.normalize_segments import (
    DEFAULT_CONTEXT_BUDGET,
    ContextBudget,
    SourceSegment,
)
from google_work_agent.application.agents.retrieval.select_evidence import select_evidence
from google_work_agent.application.orchestration.contracts import RunBudgetV1
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.ports.llm import PromptReference
from google_work_agent.ports.system.contracts.observability import ObservabilityContext

from ..projections.select_evidence_projection import (
    project_select_evidence_input,
)
from ..state import RetrievalStateV2


def select_evidence_node(
    state: RetrievalStateV2,
    *,
    llm_runtime: StructuredLLMRuntime,
    prompt_ref: PromptReference,
    revision_prompt_ref: PromptReference,
    trace_context: ObservabilityContext,
    segments: list[SourceSegment],
    retry_budget: RunBudgetV1,
    context_budget: ContextBudget = DEFAULT_CONTEXT_BUDGET,
) -> dict[str, object]:
    projection = project_select_evidence_input(state)
    selection, revised_budget = select_evidence(
        llm_runtime=llm_runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=revision_prompt_ref,
        trace_context=trace_context,
        segments=segments,
        retry_budget=retry_budget,
        context_budget=context_budget,
        **projection,
    )
    return {
        "evidence_selection": selection,
        "retry_budget": revised_budget,
    }
