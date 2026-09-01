from __future__ import annotations

from google_work_agent.application.agents.retrieval.normalize_segments import (
    DEFAULT_CONTEXT_BUDGET,
    ContextBudget,
    SourceSegment,
)
from google_work_agent.application.agents.retrieval.select_evidence import select_evidence
from google_work_agent.application.use_cases.run.guard_run_budget import (
    RunBudgetV2,
)
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1

from ..projections.select_evidence_projection import (
    project_select_evidence_input,
)
from ..state import RetrievalState


def select_evidence_node(
    state: RetrievalState,
    *,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    revision_prompt_ref: PromptReference,
    requested_mode: RequestedModeV1,
    segments: list[SourceSegment],
    retry_budget: RunBudgetV2,
    context_budget: ContextBudget = DEFAULT_CONTEXT_BUDGET,
) -> dict[str, object]:
    projection = project_select_evidence_input(state)
    selection, revised_budget = select_evidence(
        llm_runtime=llm_runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=revision_prompt_ref,
        requested_mode=requested_mode,
        segments=segments,
        retry_budget=retry_budget,
        context_budget=context_budget,
        **projection,
    )
    return {
        "evidence_selection": selection,
        "retry_budget": revised_budget,
    }
