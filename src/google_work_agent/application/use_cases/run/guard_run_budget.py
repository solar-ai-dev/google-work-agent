"""Canonical deterministic controller for one Run's frozen runtime budget."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Required, TypedDict, cast


class BudgetProfile(StrEnum):
    NORMAL = "NORMAL"
    REVISION_HEAVY = "REVISION_HEAVY"
    RETRIEVAL_HEAVY = "RETRIEVAL_HEAVY"


class BudgetDecision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class BudgetReasonCode(StrEnum):
    PROFILE_LLM_LIMIT_EXHAUSTED = "PROFILE_LLM_LIMIT_EXHAUSTED"
    ABSOLUTE_LLM_LIMIT_EXHAUSTED = "ABSOLUTE_LLM_LIMIT_EXHAUSTED"
    ADDITIONAL_ACQUISITION_LIMIT_EXHAUSTED = "ADDITIONAL_ACQUISITION_LIMIT_EXHAUSTED"
    PLANNING_REVISION_LIMIT_EXHAUSTED = "PLANNING_REVISION_LIMIT_EXHAUSTED"
    REVIEW_RECHECK_LIMIT_EXHAUSTED = "REVIEW_RECHECK_LIMIT_EXHAUSTED"
    SEMANTIC_SAME_FAILURE_LIMIT_EXHAUSTED = "SEMANTIC_SAME_FAILURE_LIMIT_EXHAUSTED"


SCHEMA_REPAIR_PER_NODE_CALL = 1
SEMANTIC_REVISION_SAME_FAILURE = 1
PLANNING_REVISION_PER_RUN = 2
REVIEW_RECHECK_PER_PLANNING_REVISION = 1
MAX_ADDITIONAL_ACQUISITIONS = 2
NORMAL_MAX_LLM_CALLS = 14
REVISION_HEAVY_MAX_LLM_CALLS = 18
RETRIEVAL_HEAVY_MAX_LLM_CALLS = 20
ABSOLUTE_MAX_LLM_CALLS = 24

_PROFILE_LIMITS = {
    BudgetProfile.NORMAL: NORMAL_MAX_LLM_CALLS,
    BudgetProfile.REVISION_HEAVY: REVISION_HEAVY_MAX_LLM_CALLS,
    BudgetProfile.RETRIEVAL_HEAVY: RETRIEVAL_HEAVY_MAX_LLM_CALLS,
}
_PROFILE_ORDER = {
    BudgetProfile.NORMAL: 0,
    BudgetProfile.REVISION_HEAVY: 1,
    BudgetProfile.RETRIEVAL_HEAVY: 2,
}


class SemanticFailureSignatureV1(TypedDict):
    schema_version: Required[Literal[1]]
    node_id: str
    failure_reason_codes: list[str]


class RunBudgetV2(TypedDict):
    schema_version: Literal[2]
    profile: Literal["NORMAL", "RETRIEVAL_HEAVY", "REVISION_HEAVY"]
    started_at_ms: int
    max_execution_ms: int
    llm_calls_used: int
    llm_call_limit: int
    connector_calls_used: int
    max_connector_calls: int
    source_page_calls_used: int
    max_source_page_calls: int
    detail_fetches_used: int
    max_detail_fetches: int
    context_tokens_used: int
    max_context_tokens: int
    retry_attempts_used: int
    max_retry_attempts: int
    absolute_llm_call_limit: Literal[24]
    schema_repairs_used_by_node: dict[str, int]
    semantic_revisions_used_by_failure: dict[str, int]
    planning_revisions_used: int
    review_rechecks_used: int
    additional_retrieval_rounds_used: int


class BudgetDecisionV1(TypedDict):
    schema_version: Required[Literal[1]]
    decision: Literal["ALLOW", "DENY"]
    budget_reason_code: (
        Literal[
            "PROFILE_LLM_LIMIT_EXHAUSTED",
            "ABSOLUTE_LLM_LIMIT_EXHAUSTED",
            "ADDITIONAL_ACQUISITION_LIMIT_EXHAUSTED",
            "PLANNING_REVISION_LIMIT_EXHAUSTED",
            "REVIEW_RECHECK_LIMIT_EXHAUSTED",
            "SEMANTIC_SAME_FAILURE_LIMIT_EXHAUSTED",
        ]
        | None
    )
    run_budget: RunBudgetV2


type RunBudgetOperationKindV1 = Literal[
    "LLM_CALL",
    "CONNECTOR_CALL",
    "SOURCE_PAGE",
    "DETAIL_FETCH",
    "RETRY_ATTEMPT",
    "CONTEXT_MATERIALIZATION",
]


@dataclass(frozen=True, slots=True)
class RunBudgetDeltaV1:
    schema_version: Literal[1]
    operation_kind: RunBudgetOperationKindV1
    units: int


@dataclass(frozen=True, slots=True)
class GuardRunBudgetQueryV1:
    schema_version: Literal[1]
    run_id: str
    current_budget: RunBudgetV2
    requested_delta: RunBudgetDeltaV1
    now_ms: int


@dataclass(frozen=True, slots=True)
class GuardRunBudgetResultV1:
    schema_version: Literal[1]
    allowed: bool
    reason_code: Literal[
        "OK",
        "MAX_EXECUTION_TIME",
        "LLM_LIMIT",
        "CONNECTOR_LIMIT",
        "SOURCE_PAGE_LIMIT",
        "DETAIL_FETCH_LIMIT",
        "RETRY_LIMIT",
        "CONTEXT_LIMIT",
    ]
    remaining_units: int
    elapsed_ms: int


_DIMENSIONS: dict[RunBudgetOperationKindV1, tuple[str, str, str]] = {
    "LLM_CALL": ("llm_calls_used", "llm_call_limit", "LLM_LIMIT"),
    "CONNECTOR_CALL": ("connector_calls_used", "max_connector_calls", "CONNECTOR_LIMIT"),
    "SOURCE_PAGE": ("source_page_calls_used", "max_source_page_calls", "SOURCE_PAGE_LIMIT"),
    "DETAIL_FETCH": ("detail_fetches_used", "max_detail_fetches", "DETAIL_FETCH_LIMIT"),
    "RETRY_ATTEMPT": ("retry_attempts_used", "max_retry_attempts", "RETRY_LIMIT"),
    "CONTEXT_MATERIALIZATION": ("context_tokens_used", "max_context_tokens", "CONTEXT_LIMIT"),
}


class GuardRunBudgetHandler:
    def __call__(self, query: GuardRunBudgetQueryV1) -> GuardRunBudgetResultV1:
        if (
            query.schema_version != 1
            or not query.run_id.strip()
            or query.requested_delta.schema_version != 1
            or query.requested_delta.units < 1
            or query.now_ms < 0
        ):
            raise ValueError("invalid run-budget query")
        budget = validate_run_budget_v2(query.current_budget)
        elapsed_ms = max(0, query.now_ms - budget["started_at_ms"])
        if elapsed_ms >= budget["max_execution_ms"]:
            return GuardRunBudgetResultV1(1, False, "MAX_EXECUTION_TIME", 0, elapsed_ms)

        used_name, limit_name, reason = _DIMENSIONS[query.requested_delta.operation_kind]
        used = int(budget[used_name])  # type: ignore[literal-required]
        limit = int(budget[limit_name])  # type: ignore[literal-required]
        if query.requested_delta.operation_kind == "LLM_CALL":
            limit = min(limit, budget["absolute_llm_call_limit"])
        remaining = max(0, limit - used)
        if query.requested_delta.units > remaining:
            return GuardRunBudgetResultV1(
                1,
                False,
                cast(
                    Literal[
                        "LLM_LIMIT",
                        "CONNECTOR_LIMIT",
                        "SOURCE_PAGE_LIMIT",
                        "DETAIL_FETCH_LIMIT",
                        "RETRY_LIMIT",
                        "CONTEXT_LIMIT",
                    ],
                    reason,
                ),
                remaining,
                elapsed_ms,
            )
        return GuardRunBudgetResultV1(
            1, True, "OK", remaining - query.requested_delta.units, elapsed_ms
        )


def build_default_run_budget(
    *,
    started_at_ms: int = 0,
    max_execution_ms: int = 900_000,
    max_connector_calls: int = 50,
    max_source_page_calls: int = 8,
    max_detail_fetches: int = 12,
    max_context_tokens: int = 16_000,
    max_retry_attempts: int = 2,
) -> RunBudgetV2:
    return validate_run_budget_v2(
        {
            "schema_version": 2,
            "profile": BudgetProfile.NORMAL.value,
            "started_at_ms": started_at_ms,
            "max_execution_ms": max_execution_ms,
            "llm_calls_used": 0,
            "llm_call_limit": NORMAL_MAX_LLM_CALLS,
            "connector_calls_used": 0,
            "max_connector_calls": max_connector_calls,
            "source_page_calls_used": 0,
            "max_source_page_calls": min(max_source_page_calls, 8),
            "detail_fetches_used": 0,
            "max_detail_fetches": min(max_detail_fetches, 12),
            "context_tokens_used": 0,
            "max_context_tokens": max_context_tokens,
            "retry_attempts_used": 0,
            "max_retry_attempts": max_retry_attempts,
            "absolute_llm_call_limit": ABSOLUTE_MAX_LLM_CALLS,
            "schema_repairs_used_by_node": {},
            "semantic_revisions_used_by_failure": {},
            "planning_revisions_used": 0,
            "review_rechecks_used": 0,
            "additional_retrieval_rounds_used": 0,
        }
    )


def validate_run_budget_v2(value: object) -> RunBudgetV2:
    if not isinstance(value, dict):
        raise ValueError("run budget must be an object")
    required = set(RunBudgetV2.__annotations__)
    missing, extra = required - set(value), set(value) - required
    if missing:
        raise ValueError(f"run budget missing required fields: {sorted(missing)}")
    if extra:
        raise ValueError(f"run budget has unsupported fields: {sorted(extra)}")
    if value["schema_version"] != 2:
        raise ValueError("run budget schema_version must be 2")
    profile = _require_profile(value["profile"])
    positive = (
        "max_execution_ms",
        "llm_call_limit",
        "max_connector_calls",
        "max_source_page_calls",
        "max_detail_fetches",
        "max_context_tokens",
    )
    non_negative = (
        "started_at_ms",
        "llm_calls_used",
        "connector_calls_used",
        "source_page_calls_used",
        "detail_fetches_used",
        "context_tokens_used",
        "retry_attempts_used",
        "max_retry_attempts",
        "planning_revisions_used",
        "review_rechecks_used",
        "additional_retrieval_rounds_used",
    )
    for field in positive:
        _require_int(value[field], field, minimum=1)
    for field in non_negative:
        _require_int(value[field], field, minimum=0)
    if value["absolute_llm_call_limit"] != ABSOLUTE_MAX_LLM_CALLS:
        raise ValueError("run budget absolute_llm_call_limit must be 24")
    if int(value["max_source_page_calls"]) > 8:
        raise ValueError("run budget max_source_page_calls exceeds retrieval hard bound")
    if int(value["max_detail_fetches"]) > 12:
        raise ValueError("run budget max_detail_fetches exceeds retrieval hard bound")
    if int(value["planning_revisions_used"]) > PLANNING_REVISION_PER_RUN:
        raise ValueError("run budget planning_revisions_used exceeds the frozen limit")
    if int(value["review_rechecks_used"]) > int(value["planning_revisions_used"]):
        raise ValueError("run budget review_rechecks_used exceeds planning revisions")
    if int(value["additional_retrieval_rounds_used"]) > MAX_ADDITIONAL_ACQUISITIONS:
        raise ValueError("run budget additional_retrieval_rounds_used exceeds the frozen limit")
    expected_limit = _effective_profile_limit(profile, value)
    if int(value["llm_call_limit"]) != expected_limit:
        raise ValueError("run budget llm_call_limit does not match the active profile")
    repairs = _validated_counter_map(value["schema_repairs_used_by_node"], "schema repairs")
    revisions = _validated_counter_map(
        value["semantic_revisions_used_by_failure"], "semantic revisions"
    )
    return cast(
        RunBudgetV2,
        {
            **value,
            "profile": profile.value,
            "schema_repairs_used_by_node": repairs,
            "semantic_revisions_used_by_failure": revisions,
        },
    )


def build_semantic_failure_signature_v1(
    *, node_id: str, failure_reason_codes: list[str]
) -> SemanticFailureSignatureV1:
    return validate_semantic_failure_signature_v1(
        {
            "schema_version": 1,
            "node_id": node_id,
            "failure_reason_codes": failure_reason_codes,
        }
    )


def validate_semantic_failure_signature_v1(value: object) -> SemanticFailureSignatureV1:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "node_id",
        "failure_reason_codes",
    }:
        raise ValueError("semantic failure signature must have exact fields")
    if (
        value["schema_version"] != 1
        or not isinstance(value["node_id"], str)
        or not value["node_id"]
    ):
        raise ValueError("semantic failure signature is invalid")
    reasons = value["failure_reason_codes"]
    if (
        not isinstance(reasons, list)
        or not reasons
        or not all(isinstance(item, str) and item for item in reasons)
    ):
        raise ValueError("semantic failure signature reason codes are invalid")
    canonical = sorted(set(reasons))
    return {
        "schema_version": 1,
        "node_id": value["node_id"],
        "failure_reason_codes": canonical,
    }


def check_llm_call_budget(
    run_budget: object, *, provider_calls_requested: int = 1
) -> BudgetDecisionV1:
    budget = validate_run_budget_v2(run_budget)
    requested = _require_int(provider_calls_requested, "provider_calls_requested", minimum=1)
    prospective = budget["llm_calls_used"] + requested
    if prospective > budget["absolute_llm_call_limit"]:
        return _deny(budget, BudgetReasonCode.ABSOLUTE_LLM_LIMIT_EXHAUSTED)
    if prospective > budget["llm_call_limit"]:
        return _deny(budget, BudgetReasonCode.PROFILE_LLM_LIMIT_EXHAUSTED)
    return _allow(budget)


def consume_llm_provider_calls(
    run_budget: object, *, provider_calls_consumed: int = 1
) -> RunBudgetV2:
    budget = validate_run_budget_v2(run_budget)
    consumed = _require_int(provider_calls_consumed, "provider_calls_consumed", minimum=1)
    updated = dict(budget)
    updated["llm_calls_used"] = budget["llm_calls_used"] + consumed
    return validate_run_budget_v2(updated)


def approve_additional_acquisition(run_budget: object) -> BudgetDecisionV1:
    budget = validate_run_budget_v2(run_budget)
    if budget["additional_retrieval_rounds_used"] >= MAX_ADDITIONAL_ACQUISITIONS:
        return _deny(budget, BudgetReasonCode.ADDITIONAL_ACQUISITION_LIMIT_EXHAUSTED)
    updated = dict(budget)
    updated["additional_retrieval_rounds_used"] = budget["additional_retrieval_rounds_used"] + 1
    return _allow(_promote(cast(RunBudgetV2, updated), BudgetProfile.RETRIEVAL_HEAVY))


def approve_planning_revision(run_budget: object) -> BudgetDecisionV1:
    budget = validate_run_budget_v2(run_budget)
    if budget["planning_revisions_used"] >= PLANNING_REVISION_PER_RUN:
        return _deny(budget, BudgetReasonCode.PLANNING_REVISION_LIMIT_EXHAUSTED)
    updated = dict(budget)
    updated["planning_revisions_used"] = budget["planning_revisions_used"] + 1
    return _allow(_promote(cast(RunBudgetV2, updated), BudgetProfile.REVISION_HEAVY))


def approve_review_recheck(run_budget: object) -> BudgetDecisionV1:
    budget = validate_run_budget_v2(run_budget)
    if (
        budget["planning_revisions_used"] <= 0
        or budget["review_rechecks_used"] >= budget["planning_revisions_used"]
    ):
        return _deny(budget, BudgetReasonCode.REVIEW_RECHECK_LIMIT_EXHAUSTED)
    updated = dict(budget)
    updated["review_rechecks_used"] = budget["review_rechecks_used"] + 1
    return _allow(validate_run_budget_v2(updated))


def approve_semantic_revision(
    run_budget: object, *, signature: SemanticFailureSignatureV1
) -> BudgetDecisionV1:
    budget = validate_run_budget_v2(run_budget)
    canonical = validate_semantic_failure_signature_v1(signature)
    key = canonical["node_id"] + "\x1f" + "\x1f".join(canonical["failure_reason_codes"])
    if (
        budget["semantic_revisions_used_by_failure"].get(key, 0)
        >= SEMANTIC_REVISION_SAME_FAILURE
    ):
        return _deny(budget, BudgetReasonCode.SEMANTIC_SAME_FAILURE_LIMIT_EXHAUSTED)
    updated = dict(budget)
    revisions = dict(budget["semantic_revisions_used_by_failure"])
    revisions[key] = revisions.get(key, 0) + 1
    updated["semantic_revisions_used_by_failure"] = revisions
    return _allow(validate_run_budget_v2(updated))


def promote_budget_profile(current_profile: object, requested_profile: object) -> BudgetProfile:
    current, requested = _require_profile(current_profile), _require_profile(requested_profile)
    return requested if _PROFILE_ORDER[requested] > _PROFILE_ORDER[current] else current


def promote_run_budget_profile(
    run_budget: object, requested_profile: object
) -> RunBudgetV2:
    return _promote(validate_run_budget_v2(run_budget), _require_profile(requested_profile))


def _promote(budget: RunBudgetV2, requested: BudgetProfile) -> RunBudgetV2:
    updated = dict(budget)
    profile = promote_budget_profile(budget["profile"], requested)
    updated["profile"] = profile.value
    updated["llm_call_limit"] = _effective_profile_limit(profile, updated)
    return validate_run_budget_v2(updated)


def _effective_profile_limit(profile: BudgetProfile, budget: object) -> int:
    if isinstance(budget, dict) and int(budget.get("planning_revisions_used", 0)) > 0 and (
        int(budget.get("additional_retrieval_rounds_used", 0)) > 0
        or profile is BudgetProfile.RETRIEVAL_HEAVY
    ):
        return ABSOLUTE_MAX_LLM_CALLS
    return _PROFILE_LIMITS[profile]


def _allow(run_budget: RunBudgetV2) -> BudgetDecisionV1:
    return {
        "schema_version": 1,
        "decision": "ALLOW",
        "budget_reason_code": None,
        "run_budget": run_budget,
    }


def _deny(run_budget: RunBudgetV2, reason: BudgetReasonCode) -> BudgetDecisionV1:
    return {
        "schema_version": 1,
        "decision": "DENY",
        "budget_reason_code": reason.value,
        "run_budget": run_budget,
    }


def _require_profile(value: object) -> BudgetProfile:
    try:
        return BudgetProfile(cast(str, value))
    except (TypeError, ValueError) as error:
        raise ValueError("run budget profile is invalid") from error


def _require_int(value: object, field: str, *, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        qualifier = "positive" if minimum == 1 else "non-negative"
        raise ValueError(f"run budget {field} must be {qualifier}")
    return value


def _validated_counter_map(value: object, field: str) -> dict[str, int]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str)
        and key
        and isinstance(count, int)
        and not isinstance(count, bool)
        and count >= 0
        for key, count in value.items()
    ):
        raise ValueError(f"run budget {field} must be a non-negative counter map")
    return dict(value)


__all__ = [
    "ABSOLUTE_MAX_LLM_CALLS",
    "BudgetDecision",
    "BudgetDecisionV1",
    "BudgetProfile",
    "BudgetReasonCode",
    "GuardRunBudgetHandler",
    "GuardRunBudgetQueryV1",
    "GuardRunBudgetResultV1",
    "MAX_ADDITIONAL_ACQUISITIONS",
    "PLANNING_REVISION_PER_RUN",
    "NORMAL_MAX_LLM_CALLS",
    "REVISION_HEAVY_MAX_LLM_CALLS",
    "RETRIEVAL_HEAVY_MAX_LLM_CALLS",
    "RunBudgetDeltaV1",
    "RunBudgetOperationKindV1",
    "RunBudgetV2",
    "SemanticFailureSignatureV1",
    "approve_additional_acquisition",
    "approve_planning_revision",
    "approve_review_recheck",
    "approve_semantic_revision",
    "build_default_run_budget",
    "build_semantic_failure_signature_v1",
    "check_llm_call_budget",
    "consume_llm_provider_calls",
    "promote_budget_profile",
    "promote_run_budget_profile",
    "validate_run_budget_v2",
    "validate_semantic_failure_signature_v1",
]
