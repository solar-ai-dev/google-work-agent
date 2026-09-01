from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import (
    WorkAnalysisLocalState,
    WorkAnalysisStateV2,
)
from google_work_agent.application.agents.work_analysis.resolve_temporal_dependencies import (
    resolve_temporal_dependencies,
)
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1

from ..projections.resolve_temporal_dependencies_projection import (
    project_resolve_temporal_dependencies_input,
)


def resolve_temporal_dependencies_node(
    state: WorkAnalysisLocalState,
    *,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    requested_mode: RequestedModeV1,
    confirmation_response: dict[str, object] | None = None,
) -> WorkAnalysisStateV2:
    return {
        "temporal_dependency_candidates": resolve_temporal_dependencies(
            **project_resolve_temporal_dependencies_input(state),
            llm_runtime=llm_runtime,
            prompt_ref=prompt_ref,
            requested_mode=requested_mode,
            confirmation_response=confirmation_response,
        )
    }
