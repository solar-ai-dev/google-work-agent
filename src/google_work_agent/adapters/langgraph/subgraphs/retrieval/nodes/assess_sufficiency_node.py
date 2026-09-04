from __future__ import annotations

from collections.abc import Collection

from google_work_agent.application.agents.retrieval.assess_sufficiency import assess_sufficiency
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
    EvidenceDraftV1,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    RunBudgetV2,
)
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
)
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1

from ..projections.assess_sufficiency_projection import (
    project_assess_sufficiency_input,
)
from ..state import RetrievalState


def assess_sufficiency_node(
    state: RetrievalState,
    *,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    requested_mode: RequestedModeV1,
    tool_route_plan: ToolRoutePlanV2 | None,
    acquisition_result: AcquisitionResultV1,
    evidence_drafts: list[EvidenceDraftV1],
    retry_budget: RunBudgetV2,
    confirmation_response: ConfirmationResponseProjectionV1 | None = None,
    attempted_detail_candidate_refs: Collection[str] = (),
) -> dict[str, object]:
    projection = project_assess_sufficiency_input(state)
    return {
        "sufficiency": assess_sufficiency(
            llm_runtime=llm_runtime,
            prompt_ref=prompt_ref,
            requested_mode=requested_mode,
            request_intent=projection["request_intent"],
            tool_route_plan=tool_route_plan,
            acquisition_result=acquisition_result,
            evidence_drafts=evidence_drafts,
            retry_budget=retry_budget,
            confirmation_response=confirmation_response,
            attempted_detail_candidate_refs=attempted_detail_candidate_refs,
        )
    }
