"""Canonical Retrieval semantic operation: assess_sufficiency."""

from __future__ import annotations

from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)
from google_work_agent.application.orchestration.contracts import (
    ConfirmationResponseProjectionV1,
    RunBudgetV1,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    AcquisitionResultV1,
    EvidenceDraftV1,
    RequestIntentV2,
    SufficiencyResultV2,
)
from google_work_agent.application.orchestration.retrieval_sufficiency import (
    SUFFICIENCY_OUTPUT_SCHEMA,
    budget_state_prompt_projection,
    enforce_sufficiency_guard,
    selected_evidence_prompt_projection,
    source_statuses_prompt_projection,
    validate_sufficiency_result_v2,
)
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.ports.events.observability_events import ObservabilityContext
from google_work_agent.ports.llm import PromptReference


def assess_sufficiency(
    *,
    llm_runtime: StructuredLLMRuntime,
    prompt_ref: PromptReference,
    trace_context: ObservabilityContext,
    request_intent: RequestIntentV2,
    tool_route_plan: ToolRoutePlanV2 | None,
    acquisition_result: AcquisitionResultV1,
    evidence_drafts: list[EvidenceDraftV1],
    retry_budget: RunBudgetV1,
    confirmation_response: ConfirmationResponseProjectionV1 | None = None,
) -> SufficiencyResultV2:
    """Assess evidence completeness, then apply the deterministic insufficient-data guard."""
    prompt_input: dict[str, object] = {
        "request_intent": request_intent,
        "selected_evidence": selected_evidence_prompt_projection(evidence_drafts),
        "source_statuses": source_statuses_prompt_projection(
            tool_route_plan=tool_route_plan,
            acquisition_result=acquisition_result,
        ),
        "budget_state": budget_state_prompt_projection(retry_budget),
    }
    if confirmation_response is not None:
        prompt_input["confirmation_response"] = dict(confirmation_response)
    result = llm_runtime.invoke_structured(
        prompt_ref=prompt_ref,
        prompt_input=prompt_input,
        output_schema=SUFFICIENCY_OUTPUT_SCHEMA,
        trace_context=trace_context,
        semantic_validate=validate_sufficiency_result_v2,
    )
    validated = validate_sufficiency_result_v2(result.structured_output)
    return enforce_sufficiency_guard(
        validated,
        request_intent=request_intent,
        retry_budget=retry_budget,
        evidence_supported_partial_possible=bool(evidence_drafts),
    )
