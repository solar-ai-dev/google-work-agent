from __future__ import annotations

from google_work_agent.application.agents.retrieval.finalize_retrieval import finalize_retrieval
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    AcquisitionResultV1,
    EvidenceDraftV1,
    RetrievalResultV1,
)

from ..projections.finalize_retrieval_projection import (
    project_finalize_retrieval_input,
)
from ..state import RetrievalStateV2


def finalize_retrieval_node(
    state: RetrievalStateV2,
    *,
    artifact_id: str,
    tool_route_plan: ToolRoutePlanV2,
    acquisition_result: AcquisitionResultV1,
    evidence_drafts: list[EvidenceDraftV1],
    current_round_no: int,
    prior_result: RetrievalResultV1 | None = None,
) -> dict[str, object]:
    projection = project_finalize_retrieval_input(state)
    return {
        "final_result": finalize_retrieval(
            artifact_id=artifact_id,
            tool_route_plan=tool_route_plan,
            acquisition_result=acquisition_result,
            evidence_drafts=evidence_drafts,
            current_round_no=current_round_no,
            prior_result=prior_result,
            **projection,
        )
    }
