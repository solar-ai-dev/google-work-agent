from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import (
    WorkAnalysisLocalState,
    WorkAnalysisStateV2,
)
from google_work_agent.application.agents.work_analysis import (
    detect_duplicate_conflict_candidates as duplicate_conflict_detector,
)
from google_work_agent.ports.llm import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1

from ..projections.detect_duplicate_conflict_candidates_projection import (
    project_detect_duplicate_conflict_candidates_input,
)

_detect_duplicate_conflicts = duplicate_conflict_detector.detect_duplicate_conflict_candidates


def detect_duplicate_conflict_candidates_node(
    state: WorkAnalysisLocalState,
    *,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    requested_mode: RequestedModeV1,
    confirmation_response: dict[str, object] | None = None,
) -> WorkAnalysisStateV2:
    return {
        "duplicate_conflict_candidates": _detect_duplicate_conflicts(
            **project_detect_duplicate_conflict_candidates_input(state),
            llm_runtime=llm_runtime,
            prompt_ref=prompt_ref,
            requested_mode=requested_mode,
            confirmation_response=confirmation_response,
        )
    }
