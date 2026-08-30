from __future__ import annotations

from typing import cast

from google_work_agent.adapters.langgraph.subgraphs.work_analysis.projections.assess_operational_risks_projection import (  # noqa: E501
    project_assess_operational_risks_input,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import WorkAnalysisStateV2
from google_work_agent.application.agents.work_analysis.assess_operational_risks import (
    assess_operational_risks,
)
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.ports.llm import PromptReference
from google_work_agent.ports.system.contracts.observability import ObservabilityContext


def assess_operational_risks_node(
    state: dict[str, object],
    *,
    llm_runtime: StructuredLLMRuntime,
    prompt_ref: PromptReference,
    trace_context: ObservabilityContext,
) -> WorkAnalysisStateV2:
    assessment = assess_operational_risks(
        **project_assess_operational_risks_input(state),
        llm_runtime=llm_runtime,
        prompt_ref=prompt_ref,
        trace_context=trace_context,
    )
    return cast(
        WorkAnalysisStateV2,
        {
            "operational_risk_candidates": list(assessment["risks"]),
            "__analysis_operational_risk_assessment__": assessment,
        },
    )


__all__ = ["assess_operational_risks_node"]
