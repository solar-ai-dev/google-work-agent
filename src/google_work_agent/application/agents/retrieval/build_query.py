"""Canonical Retrieval deterministic operation: build_query."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from google_work_agent.application.agents.retrieval.contracts.query_attempt import QueryAttemptV1
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalConstraintKindV1,
    RetrievalV2ValidationError,
    RouteQueryIntentV2,
    SemanticRetrievalConstraintV1,
    SourceFetchPlanV1,
    validate_retrieval_query_plan_v2,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.ports.connector.connector_read_port import JsonValue


class QueryUnchangedAfterFailureError(RetrievalV2ValidationError):
    """A changed SEARCH would repeat an already-failed effective query."""


@dataclass(frozen=True, slots=True)
class RouteConstraintPolicy:
    supported_kinds: frozenset[RetrievalConstraintKindV1]
    required_kinds: frozenset[RetrievalConstraintKindV1] = frozenset()


def build_query(
    plan: object,
    *,
    frozen_routes: Sequence[InputToolRouteV1],
    route_policies: Mapping[str, RouteConstraintPolicy],
    prior_plans: Mapping[str, SourceFetchPlanV1] | None = None,
    prior_read_result_handles: Mapping[str, str] | None = None,
    validated_resource_refs: Mapping[str, Collection[str]] | None = None,
    validated_container_refs: Mapping[str, Collection[str]] | None = None,
    detail_candidate_refs: Collection[str] = (),
) -> list[SourceFetchPlanV1]:
    """Validate/merge semantic constraints and materialize deterministic read plans."""
    prior_plans = prior_plans or {}
    prior_read_result_handles = prior_read_result_handles or {}
    route_by_id = {route["route_id"]: route for route in frozen_routes}
    _validate_policies(route_by_id, route_policies)
    validated = validate_retrieval_query_plan_v2(
        plan,
        frozen_routes=frozen_routes,
        supported_constraint_kinds={
            route_id: policy.supported_kinds for route_id, policy in route_policies.items()
        },
        validated_resource_refs=validated_resource_refs,
        validated_container_refs=validated_container_refs,
        detail_candidate_refs=detail_candidate_refs,
    )
    query_by_route = {query["route_id"]: query for query in validated["route_queries"]}
    return [
        _build_one(
            query_by_route[route_id],
            route=route_by_id[route_id],
            policy=route_policies[route_id],
            prior_plan=prior_plans.get(route_id),
            prior_read_result_handle=prior_read_result_handles.get(route_id),
        )
        for route_id in validated["retrieval_order"]
    ]


def _build_one(
    query: RouteQueryIntentV2,
    *,
    route: InputToolRouteV1,
    policy: RouteConstraintPolicy,
    prior_plan: SourceFetchPlanV1 | None,
    prior_read_result_handle: str | None,
) -> SourceFetchPlanV1:
    operation = query["operation"]
    effective = (
        _effective_constraints(query, policy=policy, prior_plan=prior_plan)
        if operation in {"SEARCH", "FREEBUSY"}
        else ([] if prior_plan is None else prior_plan["effective_constraints"])
    )
    if operation == "NEXT_PAGE" and prior_read_result_handle is None:
        raise RetrievalV2ValidationError("NEXT_PAGE requires a validated prior read-result handle")
    resource_type = route["resource_type"]
    normalized = _normalize_constraints(effective)
    return {
        "schema_version": 1,
        "route_id": route["route_id"],
        "connector_id": route["connector_id"],
        "resource_type": resource_type,
        "operation_kind": operation,
        "effective_constraints": normalized,
        "query_identity_hash": (
            prior_plan["query_identity_hash"]
            if operation == "NEXT_PAGE" and prior_plan is not None
            else _query_identity(route, operation, normalized, query["detail_candidate_ref"])
        ),
        "prior_read_result_handle": prior_read_result_handle,
        "detail_candidate_ref": query["detail_candidate_ref"],
    }


def _effective_constraints(
    query: RouteQueryIntentV2,
    *,
    policy: RouteConstraintPolicy,
    prior_plan: SourceFetchPlanV1 | None,
) -> list[SemanticRetrievalConstraintV1]:
    spec = query["search_spec"]
    if spec is None:
        raise RetrievalV2ValidationError("SEARCH/FREEBUSY requires search_spec")
    if spec["mode"] == "INITIAL":
        effective = list(spec["constraints"])
    else:
        if prior_plan is None:
            raise RetrievalV2ValidationError("CHANGED SEARCH requires a prior query")
        delta = spec["constraint_delta"]
        removed = set(delta["remove_constraint_kinds"])
        if policy.required_kinds.intersection(removed):
            raise RetrievalV2ValidationError("CHANGED SEARCH removes a required constraint")
        merged = {c["kind"]: c for c in prior_plan["effective_constraints"]}
        for kind in removed:
            merged.pop(kind, None)
        for constraint in delta["upsert_constraints"]:
            merged[constraint["kind"]] = constraint
        effective = list(merged.values())
        if _canonical_constraints(effective) == _canonical_constraints(
            prior_plan["effective_constraints"]
        ):
            raise QueryUnchangedAfterFailureError("QUERY_UNCHANGED_AFTER_FAILURE")
    kinds = {constraint["kind"] for constraint in effective}
    if not policy.required_kinds.issubset(kinds):
        raise RetrievalV2ValidationError("effective constraints omit a required kind")
    return effective


def _validate_policies(
    routes: Mapping[str, InputToolRouteV1],
    policies: Mapping[str, RouteConstraintPolicy],
) -> None:
    if set(routes) != set(policies):
        raise RetrievalV2ValidationError("each frozen route requires exactly one constraint policy")
    for route_id, policy in policies.items():
        if not policy.required_kinds.issubset(policy.supported_kinds):
            raise RetrievalV2ValidationError(f"route {route_id} requires an unsupported constraint")


def _canonical_constraints(constraints: Sequence[SemanticRetrievalConstraintV1]) -> str:
    return json.dumps(list(constraints), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _normalize_constraints(
    constraints: Sequence[SemanticRetrievalConstraintV1],
) -> list[SemanticRetrievalConstraintV1]:
    return cast(
        list[SemanticRetrievalConstraintV1],
        json.loads(_canonical_constraints(constraints)),
    )


def _query_identity(
    route: InputToolRouteV1,
    operation: object,
    constraints: Sequence[SemanticRetrievalConstraintV1],
    detail_candidate_ref: object,
) -> str:
    payload = {
        "connector_id": route["connector_id"],
        "detail_candidate_ref": detail_candidate_ref,
        "effective_constraints": json.loads(_canonical_constraints(constraints)),
        "operation_kind": operation,
        "resource_type": route["resource_type"],
        "route_id": route["route_id"],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


# Preserved attempt construction is owned by this query-building operation.

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
