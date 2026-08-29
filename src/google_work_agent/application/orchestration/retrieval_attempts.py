"""Canonical Retrieval-local QueryAttempt materialization."""

from __future__ import annotations

from typing import Literal, cast

from google_work_agent.application.agents.retrieval.contracts.query_attempt import QueryAttemptV1
from google_work_agent.application.orchestration.handoff_contracts import SourceFetchPlanV1

QueryAttempt = QueryAttemptV1


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
) -> QueryAttemptV1:
    """Record only bounded normalized read meaning, never provider arguments."""
    resource_type = cast(
        Literal["EMAIL", "TASK", "CALENDAR"],
        {
            "GMAIL": "EMAIL",
            "TASKS": "TASK",
            "CALENDAR": "CALENDAR",
        }[plan["source"]],
    )
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
        "normalized_intent_constraints": [],
        "query_spec": {
            "tool_id": f"legacy:{plan['source'].lower()}:{operation_kind.lower()}",
            "tool_schema_version": "legacy-projection-v1",
            "canonical_arguments": {
                "query_identity_hash": query_hash,
                "page_size": plan["page_size"],
            },
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
    prior_query_attempts: list[QueryAttemptV1],
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
