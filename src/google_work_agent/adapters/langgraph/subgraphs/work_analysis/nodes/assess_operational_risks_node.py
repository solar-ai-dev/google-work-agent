from __future__ import annotations

from typing import cast

from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import WorkAnalysisStateV2
from google_work_agent.application.agents.work_analysis.assess_operational_risks import (
    assess_operational_risks,
)
from google_work_agent.ports.llm import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1

from ..projections.assess_operational_risks_projection import (
    project_assess_operational_risks_input,
)


def assess_operational_risks_node(
    state: dict[str, object],
    *,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    requested_mode: RequestedModeV1,
) -> WorkAnalysisStateV2:
    assessment = assess_operational_risks(
        **project_assess_operational_risks_input(state),
        llm_runtime=llm_runtime,
        prompt_ref=prompt_ref,
        requested_mode=requested_mode,
    )
    return cast(
        WorkAnalysisStateV2,
        {
            "operational_risk_candidates": list(assessment["risks"]),
            "__analysis_operational_risk_assessment__": assessment,
        },
    )


__all__ = ["assess_operational_risks_node"]
