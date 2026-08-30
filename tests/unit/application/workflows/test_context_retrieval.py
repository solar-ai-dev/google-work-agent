"""Shared Retrieval fixtures retained at the historical import path.

Behavioral coverage lives in the exact application/agents/retrieval test owners.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, cast

from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    AcquisitionResultV1,
    ContextStatusValue,
    EvidenceRoleDraftV2,
    EvidenceSelectionResultV2,
    RequestIntentV2,
    SufficiencyIssueV2,
    SufficiencyResultV2,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    RunBudgetV2,
    build_default_run_budget,
)
from google_work_agent.ports.llm import (
    ActualRuntime,
    OutputSchemaDefinition,
    PromptReference,
    RequestedRuntimeMode,
    StructuredLLMResult,
)
from google_work_agent.ports.system.contracts.observability import ObservabilityContext

SELECT_PROMPT_REF = PromptReference(
    prompt_bundle_version="test",
    prompt_id="retrieval.select_evidence",
    prompt_version="1",
    content_hash="hash",
    agent_role="retrieval",
    subgraph_name="retrieval",
    node_name="select_evidence",
    node_state="INITIAL",
    purpose="select_evidence",
    input_schema_version="1",
    output_schema_version="1",
)
SUFFICIENCY_PROMPT_REF = PromptReference(
    prompt_bundle_version="test",
    prompt_id="retrieval.assess_sufficiency",
    prompt_version="1",
    content_hash="hash",
    agent_role="retrieval",
    subgraph_name="retrieval",
    node_name="assess_sufficiency",
    node_state="INITIAL",
    purpose="assess_sufficiency",
    input_schema_version="1",
    output_schema_version="1",
)


@dataclass
class FakeLLMRuntime:
    queued: deque[StructuredLLMResult | Exception] = field(default_factory=deque)
    calls: list[dict[str, object]] = field(default_factory=list)

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
        semantic_validate: Callable[[object], object] | None = None,
    ) -> StructuredLLMResult:
        self.calls.append(
            {
                "prompt_ref": prompt_ref,
                "prompt_input": dict(prompt_input),
                "output_schema": output_schema,
                "trace_context": trace_context,
                "semantic_validate": semantic_validate,
            }
        )
        result = self.queued.popleft()
        if isinstance(result, Exception):
            raise result
        return result


def _intent() -> RequestIntentV2:
    return {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "Summarize Kim's project updates",
        "completion_conditions": ["Relevant evidence is available."],
        "constraints": [{"kind": "PERSON", "field": "person", "value": "Kim"}],
        "ambiguity": {
            "requires_confirmation": False,
            "reason_codes": [],
            "missing_fields": [],
        },
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "REQUIRED",
    }


def _tool_route_plan(routes: list[dict[str, object]] | None = None) -> ToolRoutePlanV2:
    input_routes = routes or [
        {
            "route_id": "route-gmail",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads"],
            "required": True,
            "reason_codes": [],
        }
    ]
    return cast(
        ToolRoutePlanV2,
        {
            "schema_version": 2,
            "input_plan": {
                "schema_version": 1,
                "meta": {"artifact_id": "route-plan-1", "revision": 1, "based_on": []},
                "input_routes": input_routes,
            },
            "output_plan": {
                "schema_version": 1,
                "meta": {"artifact_id": "route-out-1", "revision": 1, "based_on": []},
                "output_mode": "ANSWER",
            },
        },
    )


def _run_budget(*, used: int) -> RunBudgetV2:
    return {
        **build_default_run_budget(),
        "additional_retrieval_rounds_used": used,
    }


def _acquisition_result() -> AcquisitionResultV1:
    return {
        "schema_version": 1,
        "status": "COMPLETE",
        "resource_handles": ["gmail_thread:thread-kim"],
        "source_summaries": [
            {
                "schema_version": 1,
                "source": "GMAIL",
                "status": "COMPLETE",
                "required": True,
                "reason_codes": ["SOURCE_REQUIRED"],
                "resource_count": 1,
                "resource_handles": ["gmail_thread:thread-kim"],
                "resources": [],
            }
        ],
        "missing_slots": [],
        "remaining_budget": {"sources": 2, "pages": 2, "candidates": 20, "details": 8},
    }


def _selection_output(selected_segment_ids: list[str]) -> EvidenceSelectionResultV2:
    return {
        "schema_version": 2,
        "selected_segment_ids": selected_segment_ids,
        "evidence_drafts": [
            cast(
                EvidenceRoleDraftV2,
                {
                    "segment_id": selected_segment_ids[0],
                    "role": cast(
                        Literal["SUPPORTS", "CONTRADICTS", "CONTEXT"], "SUPPORTS"
                    ),
                    "relevance_reason": "Directly answers the request.",
                },
            )
        ],
        "excluded_segment_ids": [],
    }


_STATUS_ISSUE: dict[str, SufficiencyIssueV2] = {
    "NEEDS_MORE_DATA": {
        "slot": "more context",
        "issue_type": "MISSING",
        "required": True,
        "resolution_source": "GOOGLE",
        "safety_critical": False,
        "reason_codes": ["more context"],
    },
    "NEEDS_CONFIRMATION": {
        "slot": "more context",
        "issue_type": "MISSING",
        "required": True,
        "resolution_source": "USER",
        "safety_critical": False,
        "reason_codes": ["more context"],
    },
    "ROUTE_RECONSIDERATION_REQUIRED": {
        "slot": "more context",
        "issue_type": "MISSING",
        "required": True,
        "resolution_source": "ROUTE",
        "safety_critical": False,
        "reason_codes": ["more context"],
    },
    "BLOCKED": {
        "slot": "more context",
        "issue_type": "MISSING",
        "required": True,
        "resolution_source": "POLICY",
        "safety_critical": True,
        "reason_codes": ["more context"],
    },
}


def _sufficiency_output(
    status: ContextStatusValue,
    *,
    ambiguity: dict[str, object] | None = None,
) -> SufficiencyResultV2:
    if status in {"SUFFICIENT", "PARTIAL"}:
        issues: list[SufficiencyIssueV2] = []
    elif ambiguity is not None:
        issues = [
            {
                "slot": str(ambiguity["reason_code"]),
                "issue_type": "MISSING",
                "required": True,
                "resolution_source": "USER",
                "safety_critical": False,
                "reason_codes": [str(ambiguity["question"])],
            }
        ]
    else:
        issues = [_STATUS_ISSUE[status]]
    return {"schema_version": 2, "status": status, "issues": issues}


def _llm_result(payload: object) -> StructuredLLMResult:
    return StructuredLLMResult(
        structured_output=payload,
        provider="fake",
        model="fake-model",
        requested_mode=RequestedRuntimeMode.AUTO,
        actual_runtime=ActualRuntime.API_LLM,
        input_tokens=1,
        output_tokens=1,
        total_tokens=2,
        latency_ms=1,
        estimated_cost_usd=None,
        fallback_reason=None,
        structured_output_attempts=1,
        provider_request_id="provider-request-1",
        safe_error_code=None,
    )
