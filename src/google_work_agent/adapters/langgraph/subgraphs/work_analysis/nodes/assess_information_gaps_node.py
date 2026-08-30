from __future__ import annotations

from typing import cast

from google_work_agent.adapters.langgraph.subgraphs.work_analysis.projections.assess_information_gaps_projection import (  # noqa: E501
    project_assess_information_gaps_input,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import WorkAnalysisStateV2
from google_work_agent.application.agents.work_analysis.assess_information_gaps import (
    assess_information_gaps,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    InformationGapAssessmentV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkAmbiguityV1,
)
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.ports.llm import PromptReference
from google_work_agent.ports.system.contracts.observability import ObservabilityContext


def assess_information_gaps_node(
    state: dict[str, object],
    *,
    llm_runtime: StructuredLLMRuntime,
    prompt_ref: PromptReference,
    trace_context: ObservabilityContext,
) -> WorkAnalysisStateV2:
    assessment = assess_information_gaps(
        **project_assess_information_gaps_input(state),
        llm_runtime=llm_runtime,
        prompt_ref=prompt_ref,
        trace_context=trace_context,
    )
    relation_ambiguities = [
        cast(
            WorkAmbiguityV1,
            {
                **item,
                "requires_confirmation": False
                if state.get("confirmation_response") is not None
                else item["requires_confirmation"],
            },
        )
        for item in cast(list[WorkAmbiguityV1], state.get("relation_validation_ambiguities", []))
    ]
    ambiguities = [*relation_ambiguities, *assessment["ambiguities"]]
    if assessment["disposition"] == "COMPLETE" and any(
        item["requires_confirmation"] for item in ambiguities
    ):
        requiring = next(item for item in ambiguities if item["requires_confirmation"])
        assessment = cast(
            InformationGapAssessmentV1,
            {
                **assessment,
                "disposition": "NEEDS_CONFIRMATION",
                "question": requiring["description"],
                "options": [],
                "reason_codes": [requiring["code"]],
            },
        )
    return cast(
        WorkAnalysisStateV2,
        {
            "ambiguity_candidates": ambiguities,
            "retrieval_needs": list(assessment["retrieval_needs"]),
            "__analysis_information_gap_assessment__": assessment,
        },
    )


__all__ = ["assess_information_gaps_node"]
