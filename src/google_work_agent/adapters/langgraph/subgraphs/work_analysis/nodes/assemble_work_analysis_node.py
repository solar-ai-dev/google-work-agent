from __future__ import annotations

from typing import cast

from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import WorkAnalysisStateV2
from google_work_agent.application.agents.work_analysis.assemble_work_analysis import (
    assemble_work_analysis,
)
from google_work_agent.application.agents.work_analysis.validate_work_analysis import (
    validate_work_analysis,
)

from ..projections.assemble_work_analysis_projection import (
    project_assemble_work_analysis_input,
)


def assemble_work_analysis_node(
    state: dict[str, object],
    *,
    artifact_id: str,
    revision: int = 1,
) -> WorkAnalysisStateV2:
    inputs = project_assemble_work_analysis_input(state)
    assembled = assemble_work_analysis(
        artifact_id=artifact_id,
        revision=revision,
        **inputs,
    )
    validated = validate_work_analysis(
        assembled,
        allowed_evidence_refs=set(inputs["evidence_refs"]),
        policy_confirmation_receipts=inputs["policy_confirmation_receipts"],
    )
    return cast(WorkAnalysisStateV2, {"final_analysis": validated})


__all__ = ["assemble_work_analysis_node"]
