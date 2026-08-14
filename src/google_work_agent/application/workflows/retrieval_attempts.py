"""Canonical Retrieval-local QueryAttempt materialization."""

from __future__ import annotations

from typing import Literal, Required, TypedDict, cast

from google_work_agent.application.workflows.handoff_contracts import SourceFetchPlanV1


class QueryAttempt(TypedDict):
    schema_version: Required[int]
    query_attempt_id: Required[str]
    run_id: Required[str]
    route_id: Required[str]
    round_no: Required[int]
    attempt_no: Required[int]
    resource_type: Required[Literal["EMAIL", "TASK", "CALENDAR"]]
    connector_id: Required[str]
    operation_kind: Required[Literal["SEARCH", "NEXT_PAGE", "DETAIL_FETCH", "FREEBUSY"]]
    normalized_intent_constraints: Required[dict[str, object]]
    query_spec: Required[dict[str, object]]
    previous_query_hash: Required[str | None]
    page_state_hash: Required[str | None]
    added_constraints: Required[list[str]]
    removed_constraints: Required[list[str]]
    change_reason_code: Required[str | None]
    candidate_count: Required[int | None]
    top_score: Required[float | None]
    score_margin: Required[float | None]
    confidence_band: Required[Literal["HIGH", "MEDIUM", "LOW", "NONE"] | None]
    retrieval_config_version: Required[str]
    score_config_version: Required[str]
    threshold_config_version: Required[str]
    stop_reason: Required[str | None]


# The current deterministic lexical retrieval implementation owns these
# version identifiers.  They are deliberately not inferred from an LLM or a
# provider response.
RETRIEVAL_CONFIG_VERSION = "deterministic-retrieval-v1"
SCORE_CONFIG_VERSION = "lexical-score-v1"
THRESHOLD_CONFIG_VERSION = "selection-threshold-v1"


def build_query_attempt(
    *,
    query_attempt_id: str,
    run_id: str,
    route_id: str,
    round_no: int,
    attempt_no: int,
    plan: SourceFetchPlanV1,
    connector_id: str,
    operation_kind: Literal["SEARCH", "NEXT_PAGE", "DETAIL_FETCH"],
    query_hash: str,
    previous_query_hash: str | None,
    page_state_hash: str | None,
    candidate_count: int,
    stop_reason: str | None,
) -> QueryAttempt:
    """Record only bounded normalized read meaning, never provider arguments."""
    resource_type = cast(Literal["EMAIL", "TASK", "CALENDAR"], {
        "GMAIL": "EMAIL",
        "TASKS": "TASK",
        "CALENDAR": "CALENDAR",
    }[plan["source"]])
    return {
        "schema_version": 1,
        "query_attempt_id": query_attempt_id,
        "run_id": run_id,
        "route_id": route_id,
        "round_no": round_no,
        "attempt_no": attempt_no,
        "resource_type": resource_type,
        "connector_id": connector_id,
        "operation_kind": operation_kind,
        "normalized_intent_constraints": dict(plan["constraints"]),
        "query_spec": {
            "source": plan["source"],
            "page_size": plan["page_size"],
            "max_pages": plan["max_pages"],
            "max_candidates": plan["max_candidates"],
            "detail_limit": plan["detail_limit"],
            "query_hash": query_hash,
        },
        "previous_query_hash": previous_query_hash,
        "page_state_hash": page_state_hash,
        "added_constraints": [],
        "removed_constraints": [],
        "change_reason_code": None,
        "candidate_count": candidate_count,
        "top_score": None,
        "score_margin": None,
        "confidence_band": None,
        "retrieval_config_version": RETRIEVAL_CONFIG_VERSION,
        "score_config_version": SCORE_CONFIG_VERSION,
        "threshold_config_version": THRESHOLD_CONFIG_VERSION,
        "stop_reason": stop_reason,
    }


def followup_planner_projection(
    *,
    current_round_no: int,
    prior_query_attempts: list[QueryAttempt],
    unresolved_sufficiency_issues: list[dict[str, object]],
    read_result_summaries: list[dict[str, object]],
) -> dict[str, object]:
    """Bounded local-only follow-up input; raw cache contents are excluded."""
    return {
        "current_round_no": current_round_no,
        "prior_query_attempts": prior_query_attempts,
        "unresolved_sufficiency_issues": unresolved_sufficiency_issues,
        "read_result_summaries": read_result_summaries,
    }
