"""retrieval.assess_sufficiency Prompt Input projection, output validation,
and deterministic status/budget/source-status derivation (docs/05-context-retrieval.md
SS5.7, SS19.1, SS19.2).

Owned separately from context_retrieval.py's select_evidence/finalize
responsibility once this bundle grew independent -- mirrors
retrieval_ranking.py's Q2-RAG split. ContextRetrievalAgent.assess_sufficiency
(context_retrieval.py) is the thin orchestration wrapper that calls into
this module, the same way it calls retrieval_ranking.rank_segments.
"""

from __future__ import annotations

from functools import partial
from typing import cast

import google_work_agent.application.orchestration._schema_support as _schema
from google_work_agent.application.orchestration.context_segmentation import (
    ContextRetrievalValidationError,
)
from google_work_agent.application.orchestration.contracts import (
    MAX_ADDITIONAL_ACQUISITIONS,
    ContextResult,
    RunBudgetV1,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    AcquisitionResultV1,
    ContextStatusValue,
    EvidenceDraftV1,
    MissingInformationRequiredForValue,
    MissingInformationV1,
    RequestIntentV2,
    SufficiencyIssueTypeValue,
    SufficiencyIssueV2,
    SufficiencyResolutionSourceValue,
    SufficiencyResultV2,
)
from google_work_agent.application.orchestration.insufficient_data import (
    InsufficientDataContext,
    InsufficientDataDisposition,
    InsufficientDataIssue,
    ResolutionSource,
    decide_insufficient_data,
)
from google_work_agent.application.orchestration.tool_routing import (
    ToolRoutePlanV2,
    coarse_resource_category,
)
from google_work_agent.ports import OutputSchemaDefinition

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
    context_retrieval._materialize_evidence_drafts stores the LLM's role
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
    api_acquisition._plan_query_prompt_input treats it defensively."""
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


def budget_state_prompt_projection(retry_budget: RunBudgetV1) -> dict[str, object]:
    """retrieval-sufficiency-input-v1.schema.json ``budget_state``, derived
    from the official RunBudgetV1/MAX_ADDITIONAL_ACQUISITIONS gate (docs/05
    section 13 MAX_ADDITIONAL_RETRIEVAL_ROUNDS=2) -- never a new hardcoded
    number."""
    used = retry_budget["additional_acquisitions_used"]
    return {
        "additional_rounds_used": used,
        "additional_rounds_remaining": max(MAX_ADDITIONAL_ACQUISITIONS - used, 0),
    }


def default_run_budget() -> RunBudgetV1:
    return {
        "schema_version": 1,
        "profile": "NORMAL",
        "llm_calls_used": 0,
        "additional_acquisitions_used": 0,
        "planning_revisions_used": 0,
        "last_rechecked_planning_revision": 0,
        "semantic_revision_signatures_used": [],
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
        raise ContextRetrievalValidationError("$.schema_version must be 2")
    status = _require_string(root, "status", "$")
    if status not in _CONTEXT_RESULT_VALUES:
        raise ContextRetrievalValidationError("$.status is invalid")
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
        raise ContextRetrievalValidationError(f"{path}.issue_type is invalid")
    resolution_source = _require_string(issue, "resolution_source", path)
    if resolution_source not in _RESOLUTION_SOURCE_VALUES:
        raise ContextRetrievalValidationError(f"{path}.resolution_source is invalid")
    required = issue.get("required")
    if not isinstance(required, bool):
        raise ContextRetrievalValidationError(f"{path}.required must be boolean")
    safety_critical = issue.get("safety_critical")
    if not isinstance(safety_critical, bool):
        raise ContextRetrievalValidationError(f"{path}.safety_critical must be boolean")
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
    retry_budget: RunBudgetV1,
    evidence_supported_partial_possible: bool,
) -> SufficiencyResultV2:
    """docs/05-context-retrieval.md SS19.2 결정적 종료 Guard: the LLM's
    proposed status is a candidate, never final authority. Reuses/extends
    insufficient_data.decide_insufficient_data (the same engine
    supervisor._route_additional_acquisition already uses) instead of a
    second guard engine. If the deterministic disposition disagrees with the
    LLM's status, the deterministic disposition wins."""
    read_only = all(
        effect == "READ" for effect in request_intent["requested_effect_hints"]
    )
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
    write_required_data_missing = not read_only and any(
        issue.required for issue in issues
    )
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
    Parent-facing handoff shape. Wiring this into RetrievalResultV1 itself
    (renaming ContextRetrievalResultV1's fields, adding retrieval_rounds/
    coverage/source_statuses) is Q2-E scope; this only prepares the
    conversion so ContextRetrievalResultV1.missing_slots/sufficiency stay
    correct without collapsing the two types together."""
    return [
        {
            "code": issue["slot"],
            "description": _issue_description(issue),
            "required_for": _RESOLUTION_SOURCE_TO_REQUIRED_FOR[issue["resolution_source"]],
        }
        for issue in issues
    ]


def sufficiency_ambiguity_projection(
    sufficiency_result: SufficiencyResultV2,
) -> dict[str, object] | None:
    """No structured ambiguity object exists on SufficiencyResultV2 (docs/05
    section 19 keeps Retrieval NEEDS_CONFIRMATION issues separate from
    Request Understanding's own RequestIntentV2.ambiguity -- item 19 of the
    Q2-D scope). This reconstructs only the minimal shape
    build_context_clarification_question already requires, from the first
    USER-resolution_source issue."""
    if sufficiency_result["status"] != "NEEDS_CONFIRMATION":
        return None
    for issue in sufficiency_result["issues"]:
        if issue["resolution_source"] == "USER":
            return {
                "question": _issue_description(issue),
                "reason_code": issue["slot"],
                "affected_field_paths": [],
                "options": [],
            }
    return None


# Shared with the other agent workflow modules; see _schema_support module docstring.
_require_mapping = partial(_schema.require_mapping, error_cls=ContextRetrievalValidationError)
_require_exact_keys = partial(_schema.require_exact_keys, error_cls=ContextRetrievalValidationError)
_require_int = partial(_schema.require_int, error_cls=ContextRetrievalValidationError)
_require_string = partial(_schema.require_string, error_cls=ContextRetrievalValidationError)
_require_string_list = partial(
    _schema.require_string_list, error_cls=ContextRetrievalValidationError
)
_require_list = partial(_schema.require_list, error_cls=ContextRetrievalValidationError)
