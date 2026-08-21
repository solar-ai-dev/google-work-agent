"""Canonical Retrieval deterministic operation: build_query."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast

from google_work_agent.application.workflows.retrieval_v2_contracts import (
    RetrievalConstraintKindV1,
    RetrievalV2ValidationError,
    RouteQueryIntentV2,
    SemanticRetrievalConstraintV1,
    SourceFetchPlanV1,
    validate_retrieval_query_plan_v2,
)
from google_work_agent.application.workflows.tool_routing import (
    InputToolRouteV1,
    coarse_resource_category,
)


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
    resource_type = _canonical_resource_type(route["resource_type"])
    if resource_type not in {"EMAIL", "TASK", "CALENDAR"}:
        raise RetrievalV2ValidationError("unsupported canonical retrieval resource_type")
    normalized = _normalize_constraints(effective)
    return {
        "schema_version": 1,
        "route_id": route["route_id"],
        "connector_id": route["connector_id"],
        "resource_type": cast(Literal["EMAIL", "TASK", "CALENDAR"], resource_type),
        "operation_kind": operation,
        "effective_constraints": normalized,
        "query_identity_hash": _query_identity(
            route, operation, normalized, query["detail_candidate_ref"]
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
            raise RetrievalV2ValidationError(
                f"route {route_id} requires an unsupported constraint"
            )


def _canonical_resource_type(resource_type: str) -> str:
    return resource_type if resource_type in {"EMAIL", "TASK", "CALENDAR"} else coarse_resource_category(resource_type)


def _canonical_constraints(constraints: Sequence[SemanticRetrievalConstraintV1]) -> str:
    return json.dumps(list(constraints), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _normalize_constraints(
    constraints: Sequence[SemanticRetrievalConstraintV1],
) -> list[SemanticRetrievalConstraintV1]:
    return cast(list[SemanticRetrievalConstraintV1], json.loads(_canonical_constraints(constraints)))


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
