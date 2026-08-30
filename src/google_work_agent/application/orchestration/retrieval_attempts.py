"""Canonical Retrieval-local QueryAttempt materialization."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.application.agents.retrieval.contracts.query_attempt import QueryAttemptV1
from google_work_agent.application.orchestration.retrieval_v2_contracts import SourceFetchPlanV1
from google_work_agent.ports.connector.connector_read_port import JsonValue

QueryAttempt = QueryAttemptV1

RETRIEVAL_CONFIG_VERSION = "deterministic-retrieval-v2"
SCORE_CONFIG_VERSION = "lexical-score-v1"
THRESHOLD_CONFIG_VERSION = "selection-threshold-v1"


def build_query_attempt(
    *,
    query_attempt_id: str,
    run_id: str,
    plan: SourceFetchPlanV1,
    round_no: int,
    attempt_no: int,
    tool_id: str,
    canonical_arguments: Mapping[str, JsonValue],
    previous_query_hash: str | None,
    page_state_hash: str | None,
    candidate_count: int | None,
    stop_reason: str | None,
) -> QueryAttemptV1:
    """Record validated read meaning without raw provider continuation."""
    return {
        "schema_version": 1,
        "query_attempt_id": query_attempt_id,
        "run_id": run_id,
        "route_id": plan["route_id"],
        "round_no": round_no,
        "attempt_no": attempt_no,
        "resource_type": plan["resource_type"],
        "connector_id": plan["connector_id"],
        "operation_kind": plan["operation_kind"],
        "normalized_intent_constraints": list(plan["effective_constraints"]),
        "query_spec": {
            "tool_id": tool_id,
            "tool_schema_version": "v1",
            "canonical_arguments": dict(canonical_arguments),
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
        "prior_query_attempts": cast(list[dict[str, object]], prior_query_attempts),
        "unresolved_sufficiency_issues": unresolved_sufficiency_issues,
        "read_result_summaries": read_result_summaries,
    }


__all__ = ["QueryAttempt", "build_query_attempt", "followup_planner_projection"]
