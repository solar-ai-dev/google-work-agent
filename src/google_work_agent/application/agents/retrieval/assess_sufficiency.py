"""Canonical Retrieval semantic operation: assess_sufficiency."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from typing import cast

import google_work_agent.application.agents.retrieval.contracts.schema_validation as _schema
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
    ContextResult,
    ContextStatusValue,
    EvidenceDraftV1,
    MissingInformationRequiredForValue,
    MissingInformationV1,
    SufficiencyIssueTypeValue,
    SufficiencyIssueV2,
    SufficiencyResolutionSourceValue,
    SufficiencyResultV2,
)
from google_work_agent.application.agents.retrieval.normalize_segments import (
    RetrievalValidationError,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    coarse_resource_category,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    MAX_ADDITIONAL_ACQUISITIONS,
    BudgetDecision,
    RunBudgetV2,
    approve_additional_acquisition,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
)
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1


def assess_sufficiency(
    *,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    requested_mode: RequestedModeV1,
    request_intent: RequestIntentV2,
    tool_route_plan: ToolRoutePlanV2 | None,
    acquisition_result: AcquisitionResultV1,
    evidence_drafts: list[EvidenceDraftV1],
    retry_budget: RunBudgetV2,
    confirmation_response: ConfirmationResponseProjectionV1 | None = None,
    attempted_detail_candidate_refs: Collection[str] = (),
) -> SufficiencyResultV2:
    """Assess evidence completeness, then apply the deterministic insufficient-data guard."""
    if _is_complete_selected_gmail_read(
        request_intent=request_intent,
        tool_route_plan=tool_route_plan,
        acquisition_result=acquisition_result,
        evidence_drafts=evidence_drafts,
        confirmation_response=confirmation_response,
    ):
        return {"schema_version": 2, "status": "SUFFICIENT", "issues": []}
    if _is_complete_calendar_create_policy_read(
        request_intent=request_intent,
        tool_route_plan=tool_route_plan,
        acquisition_result=acquisition_result,
        confirmation_response=confirmation_response,
    ):
        return {"schema_version": 2, "status": "SUFFICIENT", "issues": []}
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
    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        prompt_input,
        SUFFICIENCY_OUTPUT_SCHEMA,
    )
    validated = validate_sufficiency_result_v2(result.structured_output)
    validated = _remove_unowned_read_confirmations(
        validated,
        request_intent=request_intent,
    )
    validated = _fail_closed_on_empty_required_acquisition(
        validated,
        tool_route_plan=tool_route_plan,
        acquisition_result=acquisition_result,
        evidence_drafts=evidence_drafts,
    )
    validated = _require_gmail_candidate_details(
        validated,
        request_intent=request_intent,
        tool_route_plan=tool_route_plan,
        evidence_drafts=evidence_drafts,
        attempted_detail_candidate_refs=attempted_detail_candidate_refs,
    )
    return enforce_sufficiency_guard(
        validated,
        request_intent=request_intent,
        retry_budget=retry_budget,
        evidence_supported_partial_possible=bool(evidence_drafts),
    )


def _remove_unowned_read_confirmations(
    result: SufficiencyResultV2,
    *,
    request_intent: RequestIntentV2,
) -> SufficiencyResultV2:
    """Keep user-choice authority in Request Understanding for read-only runs."""

    if (
        set(request_intent["requested_effect_hints"]) != {"READ"}
        or request_intent["ambiguity"]["requires_confirmation"]
    ):
        return result
    issues = [
        issue for issue in result["issues"] if issue["resolution_source"] != "USER"
    ]
    return {"schema_version": 2, "status": result["status"], "issues": issues}


def _fail_closed_on_empty_required_acquisition(
    result: SufficiencyResultV2,
    *,
    tool_route_plan: ToolRoutePlanV2 | None,
    acquisition_result: AcquisitionResultV1,
    evidence_drafts: list[EvidenceDraftV1],
) -> SufficiencyResultV2:
    """Do not treat a completed-but-empty required lookup as evidence."""
    if (
        tool_route_plan is None
        or acquisition_result["status"] != "COMPLETE"
        or evidence_drafts
        or not any(
            route["required"] for route in tool_route_plan["input_plan"]["input_routes"]
        )
    ):
        return result
    issue: SufficiencyIssueV2 = {
        "slot": "required_source_evidence",
        "issue_type": "MISSING",
        "required": True,
        "resolution_source": "GOOGLE",
        "safety_critical": False,
        "reason_codes": ["REQUIRED_SOURCE_RETURNED_NO_RESOURCES"],
    }
    return {
        "schema_version": 2,
        "status": result["status"],
        "issues": [*result["issues"], issue],
    }


def _is_complete_selected_gmail_read(
    *,
    request_intent: RequestIntentV2,
    tool_route_plan: ToolRoutePlanV2 | None,
    acquisition_result: AcquisitionResultV1,
    evidence_drafts: list[EvidenceDraftV1],
    confirmation_response: ConfirmationResponseProjectionV1 | None,
) -> bool:
    if (
        confirmation_response is not None
        or tool_route_plan is None
        or tool_route_plan["output_plan"]["output_mode"] != "ANSWER"
        or request_intent["analysis_requirement"] != "NONE"
        or set(request_intent["requested_effect_hints"]) != {"READ"}
        or acquisition_result["status"] != "COMPLETE"
        or acquisition_result["missing_slots"]
        or not evidence_drafts
    ):
        return False
    routes = tool_route_plan["input_plan"]["input_routes"]
    if len(routes) != 1:
        return False
    route = routes[0]
    return (
        route["resource_type"] == "GMAIL_THREAD"
        and route["required"]
        and "RESOURCE_SELECTED" in route["reason_codes"]
        and all(draft["resource_handle"].startswith("gmail_thread:") for draft in evidence_drafts)
    )


def _is_complete_calendar_create_policy_read(
    *,
    request_intent: RequestIntentV2,
    tool_route_plan: ToolRoutePlanV2 | None,
    acquisition_result: AcquisitionResultV1,
    confirmation_response: ConfirmationResponseProjectionV1 | None,
) -> bool:
    """Accept a fully executed exact Calendar conflict-check plan without an LLM.

    A completed event lookup may correctly return zero resources.  Together
    with the authoritative calendar and free/busy reads this is a complete
    policy input, not a missing-data signal that should trigger a broader
    search.
    """

    if (
        confirmation_response is not None
        or tool_route_plan is None
        or request_intent["analysis_requirement"] != "NONE"
        or set(request_intent["requested_effect_hints"]) != {"CREATE"}
        or set(request_intent["requested_resource_hints"]) != {"CALENDAR_EVENT"}
        or acquisition_result["status"] != "COMPLETE"
        or acquisition_result["missing_slots"]
    ):
        return False
    output_routes = tool_route_plan["output_plan"].get("output_routes")
    if (
        tool_route_plan["output_plan"]["output_mode"] != "ACTION"
        or not isinstance(output_routes, list)
        or len(output_routes) != 1
        or not isinstance(output_routes[0], Mapping)
        or output_routes[0].get("effect") != "CREATE"
        or output_routes[0].get("resource_type") != "CALENDAR_EVENT"
    ):
        return False
    input_routes = tool_route_plan["input_plan"]["input_routes"]
    if {route["resource_type"] for route in input_routes} != {
        "CALENDAR",
        "CALENDAR_EVENT",
        "CALENDAR_FREEBUSY",
    }:
        return False
    if any(
        not route["required"]
        or route["reason_codes"] != ["POLICY_CALENDAR_CONFLICT_CHECK"]
        for route in input_routes
    ):
        return False
    summaries_by_route = {
        summary.get("route_id"): summary
        for summary in acquisition_result["source_summaries"]
        if isinstance(summary.get("route_id"), str)
    }
    return all(
        route["route_id"] in summaries_by_route
        and summaries_by_route[route["route_id"]].get("status") == "COMPLETE"
        for route in input_routes
    )


# Preserved insufficient-data policy is owned by this sufficiency operation.


class ResolutionSource(StrEnum):
    USER = "USER"
    GOOGLE = "GOOGLE"
    POLICY = "POLICY"
    ROUTE = "ROUTE"


class InsufficientDataDisposition(StrEnum):
    CONTINUE = "CONTINUE"
    BLOCKED = "BLOCKED"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    ROUTE_RECONSIDERATION_REQUIRED = "ROUTE_RECONSIDERATION_REQUIRED"
    RETRIEVE_MORE = "RETRIEVE_MORE"
    PARTIAL = "PARTIAL"


@dataclass(frozen=True, slots=True)
class InsufficientDataIssue:
    issue_type: str
    required: bool
    resolution_source: ResolutionSource
    safety_critical: bool = False


@dataclass(frozen=True, slots=True)
class InsufficientDataContext:
    issues: tuple[InsufficientDataIssue, ...]
    budget_remaining: int
    read_only: bool
    evidence_supported_partial_possible: bool
    write_required_data_missing: bool = False
    user_can_resolve_write_gap: bool = False


def decide_insufficient_data(context: InsufficientDataContext) -> InsufficientDataDisposition:
    """Apply the canonical fail-closed precedence independently of LLM confidence."""

    required = tuple(issue for issue in context.issues if issue.required)
    if any(
        issue.safety_critical or issue.resolution_source is ResolutionSource.POLICY
        for issue in required
    ):
        return InsufficientDataDisposition.BLOCKED
    if any(issue.resolution_source is ResolutionSource.USER for issue in required):
        return InsufficientDataDisposition.NEEDS_CONFIRMATION
    if any(issue.resolution_source is ResolutionSource.ROUTE for issue in required):
        return InsufficientDataDisposition.ROUTE_RECONSIDERATION_REQUIRED
    if (
        any(issue.resolution_source is ResolutionSource.GOOGLE for issue in required)
        and context.budget_remaining > 0
    ):
        return InsufficientDataDisposition.RETRIEVE_MORE
    if context.budget_remaining <= 0 and context.read_only:
        return InsufficientDataDisposition.PARTIAL
    if context.write_required_data_missing:
        if context.user_can_resolve_write_gap:
            return InsufficientDataDisposition.NEEDS_CONFIRMATION
        return InsufficientDataDisposition.BLOCKED
    if required:
        return InsufficientDataDisposition.BLOCKED
    return InsufficientDataDisposition.CONTINUE


# Preserved deterministic evaluator is owned by this sufficiency operation.

SUFFICIENCY_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="sufficiency-result-v2",
    json_schema={
        "type": "object",
        "required": ["schema_version", "status", "issues"],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "integer", "enum": [2]},
            "status": {
                "type": "string",
                "enum": [
                    "SUFFICIENT",
                    "NEEDS_MORE_DATA",
                    "NEEDS_CONFIRMATION",
                    "ROUTE_RECONSIDERATION_REQUIRED",
                    "PARTIAL",
                    "BLOCKED",
                ],
            },
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "slot",
                        "issue_type",
                        "required",
                        "resolution_source",
                        "safety_critical",
                        "reason_codes",
                    ],
                    "properties": {
                        "slot": {"type": "string"},
                        "issue_type": {"type": "string", "enum": ["MISSING", "CONFLICT"]},
                        "required": {"type": "boolean"},
                        "resolution_source": {
                            "type": "string",
                            "enum": ["USER", "GOOGLE", "POLICY", "ROUTE"],
                        },
                        "safety_critical": {"type": "boolean"},
                        "reason_codes": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    },
)

_CONTEXT_RESULT_VALUES = {item.value for item in ContextResult}
_ISSUE_TYPE_VALUES = {"MISSING", "CONFLICT"}
_RESOLUTION_SOURCE_VALUES = {"USER", "GOOGLE", "POLICY", "ROUTE"}
_RESOURCE_TYPE_TO_SOURCE_NAME: dict[str, str] = {
    "EMAIL": "GMAIL",
    "TASK": "TASKS",
    "CALENDAR": "CALENDAR",
}
_SOURCE_STATUS_MAP: dict[str, tuple[str, str | None]] = {
    "COMPLETE": ("COMPLETE", None),
    "PARTIAL": ("PARTIAL", None),
    "AUTH_REQUIRED": ("FAILED", "AUTH_REQUIRED"),
    "RATE_LIMITED": ("FAILED", "RATE_LIMITED"),
    "BUDGET_EXHAUSTED": ("FAILED", "BUDGET_EXHAUSTED"),
    "FAILED": ("FAILED", "FAILED"),
}
_SOURCE_STATUS_PRIORITY = {"COMPLETE": 1, "PARTIAL": 2, "FAILED": 3}
_DISPOSITION_TO_STATUS: dict[InsufficientDataDisposition, ContextStatusValue] = {
    InsufficientDataDisposition.CONTINUE: "SUFFICIENT",
    InsufficientDataDisposition.BLOCKED: "BLOCKED",
    InsufficientDataDisposition.NEEDS_CONFIRMATION: "NEEDS_CONFIRMATION",
    InsufficientDataDisposition.ROUTE_RECONSIDERATION_REQUIRED: "ROUTE_RECONSIDERATION_REQUIRED",
    InsufficientDataDisposition.RETRIEVE_MORE: "NEEDS_MORE_DATA",
    InsufficientDataDisposition.PARTIAL: "PARTIAL",
}
# docs/05-context-retrieval.md SS19.1 has no free-text description field and
# docs/06-agent-workflow.md SS3.3's MissingInformationV1.required_for has no
# 1:1 Canonical definition from resolution_source -- both are documented,
# deterministic Q2-D defaults for the Parent-facing projection boundary,
# not fabricated data. Q2-E owns refining them once RetrievalResultV1 itself
# is finalized.
_RESOLUTION_SOURCE_TO_REQUIRED_FOR: dict[str, MissingInformationRequiredForValue] = {
    "USER": "USER_CONFIRMATION",
    "GOOGLE": "RETRIEVAL",
    "ROUTE": "RETRIEVAL",
    "POLICY": "PLANNING",
}


def selected_evidence_prompt_projection(
    evidence_drafts: list[EvidenceDraftV1],
) -> list[dict[str, object]]:
    """retrieval-sufficiency-input-v1.schema.json ``selected_evidence``.

    Reuses select_evidence's already-materialized EvidenceDraftV1 list
    (docs/05 section 5.6 deterministic Segment join) -- assess_sufficiency
    never re-derives evidence from EvidenceSelectionResultV2/segments
    itself. role is read back from reason_codes[0], where
    select_evidence.materialize_evidence_drafts stores the LLM's role
    classification."""
    return [
        {
            "evidence_ref": draft["evidence_id"],
            "excerpt": draft["excerpt"],
            "role": draft["reason_codes"][0],
            "resource_ref": draft["resource_handle"],
        }
        for draft in evidence_drafts
    ]


def source_statuses_prompt_projection(
    *,
    tool_route_plan: ToolRoutePlanV2 | None,
    acquisition_result: AcquisitionResultV1,
) -> list[dict[str, object]]:
    """retrieval-sufficiency-input-v1.schema.json ``source_statuses``: one
    entry per frozen input_route (docs/05 SS4/CTX-002 Tool Route owns
    route_id), COMPLETE/PARTIAL/FAILED/NOT_ATTEMPTED joined from
    AcquisitionResultV1.source_summaries -- never the raw Provider/MCP
    response. tool_route_plan may be absent the same way
    The canonical plan_query prompt projection treats it defensively."""
    routes = () if tool_route_plan is None else tool_route_plan["input_plan"]["input_routes"]
    summaries_by_source: dict[str, list[dict[str, object]]] = {}
    for summary in acquisition_result["source_summaries"]:
        summaries_by_source.setdefault(str(summary.get("source")), []).append(summary)
    projections: list[dict[str, object]] = []
    for route in routes:
        resource_type = coarse_resource_category(route["resource_type"])
        source_name = _RESOURCE_TYPE_TO_SOURCE_NAME[resource_type]
        summaries = summaries_by_source.get(source_name, [])
        if not summaries:
            status, failure_kind = "NOT_ATTEMPTED", None
        else:
            status, failure_kind = _worst_source_status(summaries)
        projections.append(
            {
                "route_id": route["route_id"],
                "resource_type": resource_type,
                "status": status,
                "failure_kind": failure_kind,
            }
        )
    return projections


def _worst_source_status(summaries: list[dict[str, object]]) -> tuple[str, str | None]:
    worst_status = "COMPLETE"
    worst_failure_kind: str | None = None
    worst_priority = 0
    for summary in summaries:
        raw_status = str(summary.get("status"))
        status, failure_kind = _SOURCE_STATUS_MAP.get(raw_status, ("FAILED", raw_status))
        priority = _SOURCE_STATUS_PRIORITY.get(status, 3)
        if priority > worst_priority:
            worst_priority = priority
            worst_status = status
            worst_failure_kind = failure_kind
    return worst_status, worst_failure_kind


def budget_state_prompt_projection(retry_budget: RunBudgetV2) -> dict[str, object]:
    """retrieval-sufficiency-input-v1.schema.json ``budget_state``, derived
    from the official RunBudgetV2/MAX_ADDITIONAL_ACQUISITIONS gate (docs/05
    section 13 MAX_ADDITIONAL_RETRIEVAL_ROUNDS=2) -- never a new hardcoded
    number."""
    used = retry_budget["additional_retrieval_rounds_used"]
    return {
        "additional_rounds_used": used,
        "additional_rounds_remaining": max(MAX_ADDITIONAL_ACQUISITIONS - used, 0),
    }


def validate_sufficiency_result_v2(value: object) -> SufficiencyResultV2:
    """sufficiency-result-v2.schema.json (docs/05-context-retrieval.md SS5.7/
    SS19.1). issues[] follows the Canonical SufficiencyIssue shape
    (slot/issue_type/required/resolution_source/safety_critical/
    reason_codes) -- see SufficiencyIssueV2 docstring for why this is not
    {code,description,required_for}."""
    root = _require_mapping(value, "$")
    _require_exact_keys(root, "$", {"schema_version", "status", "issues"})
    schema_version = _require_int(root, "schema_version", "$")
    if schema_version != 2:
        raise RetrievalValidationError("$.schema_version must be 2")
    status = _require_string(root, "status", "$")
    if status not in _CONTEXT_RESULT_VALUES:
        raise RetrievalValidationError("$.status is invalid")
    issues = [
        _validate_sufficiency_issue(item, f"$.issues[{index}]")
        for index, item in enumerate(_require_list(root["issues"], "$.issues"))
    ]
    return {
        "schema_version": 2,
        "status": cast(ContextStatusValue, status),
        "issues": issues,
    }


def _validate_sufficiency_issue(value: object, path: str) -> SufficiencyIssueV2:
    issue = _require_mapping(value, path)
    _require_exact_keys(
        issue,
        path,
        {"slot", "issue_type", "required", "resolution_source", "safety_critical", "reason_codes"},
    )
    issue_type = _require_string(issue, "issue_type", path)
    if issue_type not in _ISSUE_TYPE_VALUES:
        raise RetrievalValidationError(f"{path}.issue_type is invalid")
    resolution_source = _require_string(issue, "resolution_source", path)
    if resolution_source not in _RESOLUTION_SOURCE_VALUES:
        raise RetrievalValidationError(f"{path}.resolution_source is invalid")
    required = issue.get("required")
    if not isinstance(required, bool):
        raise RetrievalValidationError(f"{path}.required must be boolean")
    safety_critical = issue.get("safety_critical")
    if not isinstance(safety_critical, bool):
        raise RetrievalValidationError(f"{path}.safety_critical must be boolean")
    return {
        "slot": _require_string(issue, "slot", path),
        "issue_type": cast(SufficiencyIssueTypeValue, issue_type),
        "required": required,
        "resolution_source": cast(SufficiencyResolutionSourceValue, resolution_source),
        "safety_critical": safety_critical,
        "reason_codes": _require_string_list(issue["reason_codes"], f"{path}.reason_codes"),
    }


def enforce_sufficiency_guard(
    sufficiency_result: SufficiencyResultV2,
    *,
    request_intent: RequestIntentV2,
    retry_budget: RunBudgetV2,
    evidence_supported_partial_possible: bool,
) -> SufficiencyResultV2:
    """docs/05-context-retrieval.md SS19.2 결정적 종료 Guard: the LLM's
    proposed status is a candidate, never final authority. Reuses/extends
    insufficient_data.decide_insufficient_data (the same engine
    supervisor._route_additional_acquisition already uses) instead of a
    second guard engine. If the deterministic disposition disagrees with the
    LLM's status, the deterministic disposition wins."""
    read_only = all(effect == "READ" for effect in request_intent["requested_effect_hints"])
    budget_state = budget_state_prompt_projection(retry_budget)
    budget_remaining = cast(int, budget_state["additional_rounds_remaining"])
    issues = tuple(
        InsufficientDataIssue(
            issue_type=issue["issue_type"],
            required=issue["required"],
            resolution_source=ResolutionSource(issue["resolution_source"]),
            safety_critical=issue["safety_critical"],
        )
        for issue in sufficiency_result["issues"]
    )
    # A survives-to-here required issue (nothing safety-critical/POLICY/
    # USER/ROUTE, and no GOOGLE issue with remaining budget) is only a
    # write-effect concern: Read-only runs fall through to the PARTIAL/
    # CONTINUE branches instead. No issue already flagged this as
    # USER-resolvable (that would have matched the NEEDS_CONFIRMATION
    # branch above it), so this never assumes a Write gap is user-fixable.
    write_required_data_missing = not read_only and any(issue.required for issue in issues)
    disposition = decide_insufficient_data(
        InsufficientDataContext(
            issues=issues,
            budget_remaining=budget_remaining,
            read_only=read_only,
            evidence_supported_partial_possible=evidence_supported_partial_possible,
            write_required_data_missing=write_required_data_missing,
            user_can_resolve_write_gap=False,
        )
    )
    authoritative_status = _DISPOSITION_TO_STATUS[disposition]
    if authoritative_status == sufficiency_result["status"]:
        return sufficiency_result
    return {
        "schema_version": 2,
        "status": authoritative_status,
        "issues": sufficiency_result["issues"],
    }


def _require_gmail_candidate_details(
    result: SufficiencyResultV2,
    *,
    request_intent: RequestIntentV2,
    tool_route_plan: ToolRoutePlanV2 | None,
    evidence_drafts: list[EvidenceDraftV1],
    attempted_detail_candidate_refs: Collection[str],
) -> SufficiencyResultV2:
    """Do not let search metadata satisfy an analysis request that needs message content."""

    if (
        tool_route_plan is None
        or request_intent["analysis_requirement"] != "REQUIRED"
        or set(request_intent["requested_effect_hints"]) != {"READ"}
        or "GMAIL_THREAD" not in request_intent["requested_resource_hints"]
    ):
        return result
    routes = tool_route_plan["input_plan"]["input_routes"]
    if not any(
        route["resource_type"] == "GMAIL_THREAD"
        and "gmail_get_thread" in route["allowed_read_tool_ids"]
        and "RESOURCE_SELECTED" not in route["reason_codes"]
        for route in routes
    ):
        return result
    attempted = set(attempted_detail_candidate_refs)
    missing_refs = {
        draft["resource_handle"]
        for draft in evidence_drafts
        if draft["resource_handle"].startswith("gmail_thread:")
        and draft["resource_handle"] not in attempted
    }
    if not missing_refs:
        return result
    issue: SufficiencyIssueV2 = {
        "slot": "gmail_candidate_detail",
        "issue_type": "MISSING",
        "required": True,
        "resolution_source": "GOOGLE",
        "safety_critical": False,
        "reason_codes": ["CANDIDATE_DETAIL_REQUIRED"],
    }
    return {
        "schema_version": 2,
        "status": result["status"],
        "issues": [
            *[
                existing
                for existing in result["issues"]
                if existing["slot"] != "gmail_candidate_detail"
            ],
            issue,
        ],
    }


def authorize_retrieval_followup(
    sufficiency_result: SufficiencyResultV2,
    *,
    request_intent: RequestIntentV2,
    retry_budget: RunBudgetV2,
    evidence_supported_partial_possible: bool,
    can_acquire_new_information: bool,
) -> tuple[SufficiencyResultV2, RunBudgetV2, bool]:
    """Charge one owner-local follow-up or normalize an exhausted result.

    ``NEEDS_MORE_DATA`` is not a Parent-facing disposition.  The Retrieval
    owner consumes the same durable Run budget used by cross-owner back-edges
    before it schedules another read.  If no slot remains, the existing
    sufficiency guard deterministically closes the result as PARTIAL/BLOCKED
    (or another non-loop disposition) instead of leaking it to Main.
    """

    if sufficiency_result["status"] != "NEEDS_MORE_DATA":
        return sufficiency_result, retry_budget, False
    if not can_acquire_new_information:
        read_only = all(
            effect == "READ" for effect in request_intent["requested_effect_hints"]
        )
        return (
            {
                "schema_version": 2,
                "status": (
                    "PARTIAL" if read_only else "BLOCKED"
                ),
                "issues": sufficiency_result["issues"],
            },
            retry_budget,
            False,
        )
    authorization = approve_additional_acquisition(retry_budget)
    if authorization["decision"] == BudgetDecision.ALLOW.value:
        return sufficiency_result, authorization["run_budget"], True
    normalized = enforce_sufficiency_guard(
        sufficiency_result,
        request_intent=request_intent,
        retry_budget=authorization["run_budget"],
        evidence_supported_partial_possible=evidence_supported_partial_possible,
    )
    return normalized, authorization["run_budget"], False


def _issue_description(issue: SufficiencyIssueV2) -> str:
    if issue["reason_codes"]:
        return "; ".join(issue["reason_codes"])
    return issue["slot"]


def missing_information_projection(
    issues: list[SufficiencyIssueV2],
) -> list[MissingInformationV1]:
    """docs/06-agent-workflow.md SS3.3 RetrievalResultV1.missing_information
    projection boundary -- deliberately not the same type as SufficiencyIssue
    (docs/05 SS19.1): SufficiencyIssue is Retrieval's own internal judgment
    input to the SS19.2 deterministic Guard, MissingInformationV1 is the
    Parent-facing handoff shape. The projection keeps those two contracts
    separate without introducing a second Retrieval result authority."""
    return [
        {
            "code": issue["slot"],
            "description": _issue_description(issue),
            "required_for": _RESOLUTION_SOURCE_TO_REQUIRED_FOR[issue["resolution_source"]],
        }
        for issue in issues
    ]


# Shared with the other agent workflow modules; see _schema_support module docstring.
_require_mapping = partial(_schema.require_mapping, error_cls=RetrievalValidationError)
_require_exact_keys = partial(_schema.require_exact_keys, error_cls=RetrievalValidationError)
_require_int = partial(_schema.require_int, error_cls=RetrievalValidationError)
_require_string = partial(_schema.require_string, error_cls=RetrievalValidationError)
_require_string_list = partial(_schema.require_string_list, error_cls=RetrievalValidationError)
_require_list = partial(_schema.require_list, error_cls=RetrievalValidationError)
