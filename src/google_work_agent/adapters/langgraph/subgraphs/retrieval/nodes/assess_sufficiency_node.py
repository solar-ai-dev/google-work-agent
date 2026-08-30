from __future__ import annotations

from google_work_agent.application.agents.retrieval.assess_sufficiency import assess_sufficiency
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)
from google_work_agent.application.orchestration.contracts import (
    ConfirmationResponseProjectionV1,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    AcquisitionResultV1,
    EvidenceDraftV1,
)
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    RunBudgetV2,
)
from google_work_agent.ports.llm import PromptReference
from google_work_agent.ports.system.contracts.observability import ObservabilityContext

from ..projections.assess_sufficiency_projection import (
    project_assess_sufficiency_input,
)
from ..state import RetrievalStateV2


def assess_sufficiency_node(
    state: RetrievalStateV2,
    *,
    llm_runtime: StructuredLLMRuntime,
    prompt_ref: PromptReference,
    trace_context: ObservabilityContext,
    tool_route_plan: ToolRoutePlanV2 | None,
    acquisition_result: AcquisitionResultV1,
    evidence_drafts: list[EvidenceDraftV1],
    retry_budget: RunBudgetV2,
    confirmation_response: ConfirmationResponseProjectionV1 | None = None,
) -> dict[str, object]:
    projection = project_assess_sufficiency_input(state)
    return {
        "sufficiency": assess_sufficiency(
            llm_runtime=llm_runtime,
            prompt_ref=prompt_ref,
            trace_context=trace_context,
            request_intent=projection["request_intent"],
            tool_route_plan=tool_route_plan,
            acquisition_result=acquisition_result,
            evidence_drafts=evidence_drafts,
            retry_budget=retry_budget,
            confirmation_response=confirmation_response,
        )
    }
