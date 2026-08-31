# ruff: noqa: E501

from google_work_agent.adapters.langgraph.subgraphs.work_analysis.projections.detect_duplicate_conflict_candidates_projection import (
    project_detect_duplicate_conflict_candidates_input,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import (
    WorkAnalysisLocalState,
    WorkAnalysisStateV2,
)
from google_work_agent.application.agents.work_analysis.detect_duplicate_conflict_candidates import (
    detect_duplicate_conflict_candidates,
)
from google_work_agent.ports.llm import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.observability import ObservabilityContext


def detect_duplicate_conflict_candidates_node(
    state: WorkAnalysisLocalState,
    *,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    trace_context: ObservabilityContext,
    confirmation_response: dict[str, object] | None = None,
) -> WorkAnalysisStateV2:
    return {
        "duplicate_conflict_candidates": detect_duplicate_conflict_candidates(
            **project_detect_duplicate_conflict_candidates_input(state),
            llm_runtime=llm_runtime,
            prompt_ref=prompt_ref,
            trace_context=trace_context,
            confirmation_response=confirmation_response,
        )
    }
