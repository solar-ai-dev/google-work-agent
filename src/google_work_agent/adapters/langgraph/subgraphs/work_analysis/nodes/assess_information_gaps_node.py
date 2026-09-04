from __future__ import annotations

from typing import cast

from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import WorkAnalysisStateV2
from google_work_agent.application.agents.work_analysis.assess_information_gaps import (
    assess_information_gaps,
    combine_information_gap_assessment,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkAmbiguityV1,
)
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1

from ..projections.assess_information_gaps_projection import (
    project_assess_information_gaps_input,
)


def assess_information_gaps_node(
    state: dict[str, object],
    *,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    requested_mode: RequestedModeV1,
) -> WorkAnalysisStateV2:
    assessment = assess_information_gaps(
        **project_assess_information_gaps_input(state),
        llm_runtime=llm_runtime,
        prompt_ref=prompt_ref,
        requested_mode=requested_mode,
    )
    assessment = combine_information_gap_assessment(
        assessment=assessment,
        relation_ambiguities=cast(
            list[WorkAmbiguityV1], state.get("relation_validation_ambiguities", [])
        ),
        request_intent=cast(WorkAnalysisStateV2, state)["request_intent"],
        has_confirmation_response=state.get("confirmation_response") is not None,
    )
    return cast(
        WorkAnalysisStateV2,
        {
            "ambiguity_candidates": list(assessment["ambiguities"]),
            "retrieval_needs": list(assessment["retrieval_needs"]),
            "__analysis_information_gap_assessment__": assessment,
        },
    )


__all__ = ["assess_information_gaps_node"]
