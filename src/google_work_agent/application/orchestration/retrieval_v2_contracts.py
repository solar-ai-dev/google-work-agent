# ruff: noqa: E501
"""Canonical Retrieval V2 DTOs and deterministic semantic validation.

This module deliberately owns no provider translation, cache access, or LLM
invocation.  It validates only the provider-neutral plan emitted by a future
Retrieval planner.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Literal, Required, TypedDict, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)

RetrievalConstraintKindV1 = Literal[
    "TEMPORAL_RANGE",
    "PARTICIPANT",
    "KEYWORD",
    "RESOURCE_REF",
    "CONTAINER_REF",
    "STATUS_SCOPE",
]
RetrievalOperationV2 = Literal["SEARCH", "NEXT_PAGE", "DETAIL_FETCH", "FREEBUSY"]
TemporalAxisV1 = Literal["MESSAGE_TIME", "TASK_SCHEDULED_DATE", "EVENT_TIME", "AVAILABILITY_WINDOW"]
ParticipantRoleV1 = Literal["ANY", "SENDER", "RECIPIENT", "ATTENDEE"]
StatusScopeValueV1 = Literal[
    "ANY", "INCOMPLETE", "COMPLETED", "DRAFT", "SENT", "CANCELLED", "CONFIRMED", "TENTATIVE"
]


class TemporalRangeConstraintV1(TypedDict):
    kind: Required[Literal["TEMPORAL_RANGE"]]
    axis: Required[TemporalAxisV1]
    start_local: Required[str | None]
    end_local: Required[str | None]
    timezone: Required[str]


class ParticipantMatchV1(TypedDict):
    role: Required[ParticipantRoleV1]
    identity: Required[str]


class ParticipantConstraintV1(TypedDict):
    kind: Required[Literal["PARTICIPANT"]]
    participants: Required[list[ParticipantMatchV1]]
    match_mode: Required[Literal["ANY", "ALL"]]


class KeywordConstraintV1(TypedDict):
    kind: Required[Literal["KEYWORD"]]
    terms: Required[list[str]]
    match_mode: Required[Literal["ANY", "ALL", "PHRASE"]]


class ResourceRefConstraintV1(TypedDict):
    kind: Required[Literal["RESOURCE_REF"]]
    resource_refs: Required[list[str]]


class ContainerRefConstraintV1(TypedDict):
    kind: Required[Literal["CONTAINER_REF"]]
    container_refs: Required[list[str]]


class StatusScopeConstraintV1(TypedDict):
    kind: Required[Literal["STATUS_SCOPE"]]
    values: Required[list[StatusScopeValueV1]]


SemanticRetrievalConstraintV1 = (
    TemporalRangeConstraintV1
    | ParticipantConstraintV1
    | KeywordConstraintV1
    | ResourceRefConstraintV1
    | ContainerRefConstraintV1
    | StatusScopeConstraintV1
)


class ConstraintDeltaV2(TypedDict):
    upsert_constraints: Required[list[SemanticRetrievalConstraintV1]]
    remove_constraint_kinds: Required[list[RetrievalConstraintKindV1]]


class InitialSearchSpecV1(TypedDict):
    mode: Required[Literal["INITIAL"]]
    constraints: Required[list[SemanticRetrievalConstraintV1]]


class ChangedSearchSpecV1(TypedDict):
    mode: Required[Literal["CHANGED"]]
    constraint_delta: Required[ConstraintDeltaV2]


SearchConstraintSpecV1 = InitialSearchSpecV1 | ChangedSearchSpecV1


class RouteQueryIntentV2(TypedDict):
    route_id: Required[str]
    operation: Required[RetrievalOperationV2]
    reason_codes: Required[list[str]]
    search_spec: Required[SearchConstraintSpecV1 | None]
    detail_candidate_ref: Required[str | None]


class RetrievalQueryPlanV2(TypedDict):
    schema_version: Required[Literal[2]]
    route_queries: Required[list[RouteQueryIntentV2]]
    required_information: Required[list[str]]
    retrieval_order: Required[list[str]]


class SourceFetchPlanV1(TypedDict):
    schema_version: Required[Literal[1]]
    route_id: Required[str]
    connector_id: Required[str]
    resource_type: Required[Literal["EMAIL", "TASK", "CALENDAR"]]
    operation_kind: Required[RetrievalOperationV2]
    effective_constraints: Required[list[SemanticRetrievalConstraintV1]]
    query_identity_hash: Required[str]
    prior_read_result_handle: Required[str | None]
    detail_candidate_ref: Required[str | None]


class RetrievalV2ValidationError(ValueError):
    """A Retrieval V2 semantic plan violates its typed authority boundary."""


_KINDS = frozenset(
    {"TEMPORAL_RANGE", "PARTICIPANT", "KEYWORD", "RESOURCE_REF", "CONTAINER_REF", "STATUS_SCOPE"}
)
_FORBIDDEN_AUTHORITY_FIELDS = frozenset(
    {
        "provider_query",
        "gmail_query",
        "raw_query",
        "page_token",
        "next_page_token",
        "continuation",
        "mcp_arguments",
        "tool_id",
    }
)


def validate_retrieval_query_plan_v2(
    value: object,
    *,
    frozen_routes: Sequence[InputToolRouteV1],
    supported_constraint_kinds: Mapping[str, Collection[RetrievalConstraintKindV1]],
    validated_resource_refs: Mapping[str, Collection[str]] | None = None,
    validated_container_refs: Mapping[str, Collection[str]] | None = None,
    detail_candidate_refs: Collection[str] = (),
) -> RetrievalQueryPlanV2:
    """Validate a V2 plan without translating it to provider syntax."""
    root = _mapping(value, "plan")
    _exact_keys(
        root, {"schema_version", "route_queries", "required_information", "retrieval_order"}, "plan"
    )
    if root["schema_version"] != 2:
        raise RetrievalV2ValidationError("plan.schema_version must be 2")
    routes = _route_map(frozen_routes)
    route_queries = root["route_queries"]
    required_information = root["required_information"]
    retrieval_order = root["retrieval_order"]
    if not isinstance(route_queries, list) or not route_queries:
        raise RetrievalV2ValidationError("plan.route_queries must be non-empty")
    if not _non_empty_strings(required_information):
        raise RetrievalV2ValidationError("plan.required_information must be non-empty strings")
    if not _non_empty_strings(retrieval_order):
        raise RetrievalV2ValidationError("plan.retrieval_order must contain unique route ids")
    retrieval_order_values = cast(list[str], retrieval_order)
    if len(set(retrieval_order_values)) != len(retrieval_order_values):
        raise RetrievalV2ValidationError("plan.retrieval_order must contain unique route ids")
    if not set(retrieval_order_values).issubset(routes):
        raise RetrievalV2ValidationError("plan.retrieval_order contains an unknown route")

    validated_queries = [
        validate_route_query_intent_v2(
            item,
            frozen_routes=routes,
            supported_constraint_kinds=supported_constraint_kinds,
            validated_resource_refs=validated_resource_refs,
            validated_container_refs=validated_container_refs,
            detail_candidate_refs=detail_candidate_refs,
        )
        for item in route_queries
    ]
    if set(retrieval_order_values) != {query["route_id"] for query in validated_queries}:
        raise RetrievalV2ValidationError("plan.retrieval_order must cover route_queries exactly")
    return {
        "schema_version": 2,
        "route_queries": validated_queries,
        "required_information": cast(list[str], required_information),
        "retrieval_order": retrieval_order_values,
    }


def validate_route_query_intent_v2(
    value: object,
    *,
    frozen_routes: Mapping[str, InputToolRouteV1],
    supported_constraint_kinds: Mapping[str, Collection[RetrievalConstraintKindV1]],
    validated_resource_refs: Mapping[str, Collection[str]] | None = None,
    validated_container_refs: Mapping[str, Collection[str]] | None = None,
    detail_candidate_refs: Collection[str] = (),
) -> RouteQueryIntentV2:
    """Validate one frozen-route operation and reject execution authority fields."""
    intent = _mapping(value, "route_query")
    _exact_keys(
        intent,
        {"route_id", "operation", "reason_codes", "search_spec", "detail_candidate_ref"},
        "route_query",
    )
    route_id = intent["route_id"]
    operation = intent["operation"]
    if not isinstance(route_id, str) or route_id not in frozen_routes:
        raise RetrievalV2ValidationError("route_query.route_id is not frozen")
    if operation not in {"SEARCH", "NEXT_PAGE", "DETAIL_FETCH", "FREEBUSY"}:
        raise RetrievalV2ValidationError("route_query.operation is invalid")
    if not _non_empty_strings(intent["reason_codes"]):
        raise RetrievalV2ValidationError("route_query.reason_codes must be non-empty strings")
    search_spec = intent["search_spec"]
    detail_candidate_ref = intent["detail_candidate_ref"]
    if operation in {"SEARCH", "FREEBUSY"}:
        if detail_candidate_ref is not None:
            raise RetrievalV2ValidationError("search operation cannot include detail_candidate_ref")
        validated_spec = validate_search_spec_v1(
            search_spec,
            route_id=route_id,
            supported_kinds=supported_constraint_kinds.get(route_id),
            validated_resource_refs=(validated_resource_refs or {}).get(route_id),
            validated_container_refs=(validated_container_refs or {}).get(route_id),
        )
    elif operation == "DETAIL_FETCH":
        if search_spec is not None:
            raise RetrievalV2ValidationError("DETAIL_FETCH cannot include search_spec")
        if (
            not isinstance(detail_candidate_ref, str)
            or detail_candidate_ref not in detail_candidate_refs
        ):
            raise RetrievalV2ValidationError(
                "DETAIL_FETCH requires a validated detail_candidate_ref"
            )
        validated_spec = None
    else:
        if search_spec is not None or detail_candidate_ref is not None:
            raise RetrievalV2ValidationError("NEXT_PAGE cannot contain semantic payload")
        validated_spec = None
    return {
        "route_id": route_id,
        "operation": cast(RetrievalOperationV2, operation),
        "reason_codes": cast(list[str], intent["reason_codes"]),
        "search_spec": validated_spec,
        "detail_candidate_ref": cast(str | None, detail_candidate_ref),
    }


def validate_search_spec_v1(
    value: object,
    *,
    route_id: str,
    supported_kinds: Collection[RetrievalConstraintKindV1] | None,
    validated_resource_refs: Collection[str] | None,
    validated_container_refs: Collection[str] | None,
) -> SearchConstraintSpecV1:
    """Validate INITIAL values or CHANGED typed delta for one frozen route."""
    if supported_kinds is None:
        raise RetrievalV2ValidationError(f"route {route_id} has no constraint policy")
    spec = _mapping(value, "search_spec")
    mode = spec.get("mode")
    if mode == "INITIAL":
        _exact_keys(spec, {"mode", "constraints"}, "search_spec")
        constraints = _validate_constraints(
            spec["constraints"],
            supported_kinds=supported_kinds,
            validated_resource_refs=validated_resource_refs,
            validated_container_refs=validated_container_refs,
        )
        return {"mode": "INITIAL", "constraints": constraints}
    if mode == "CHANGED":
        _exact_keys(spec, {"mode", "constraint_delta"}, "search_spec")
        delta = _mapping(spec["constraint_delta"], "constraint_delta")
        _exact_keys(delta, {"upsert_constraints", "remove_constraint_kinds"}, "constraint_delta")
        upserts = _validate_constraints(
            delta["upsert_constraints"],
            supported_kinds=supported_kinds,
            validated_resource_refs=validated_resource_refs,
            validated_container_refs=validated_container_refs,
            allow_empty=True,
        )
        removals = delta["remove_constraint_kinds"]
        if not isinstance(removals, list) or not all(item in _KINDS for item in removals):
            raise RetrievalV2ValidationError("constraint_delta.remove_constraint_kinds is invalid")
        if len(set(removals)) != len(removals):
            raise RetrievalV2ValidationError(
                "constraint_delta.remove_constraint_kinds is duplicated"
            )
        if not set(removals).issubset(supported_kinds):
            raise RetrievalV2ValidationError("constraint_delta removes an unsupported kind")
        if {constraint["kind"] for constraint in upserts}.intersection(removals):
            raise RetrievalV2ValidationError("constraint_delta upserts and removes the same kind")
        return {
            "mode": "CHANGED",
            "constraint_delta": {
                "upsert_constraints": upserts,
                "remove_constraint_kinds": cast(list[RetrievalConstraintKindV1], removals),
            },
        }
    raise RetrievalV2ValidationError("search_spec.mode must be INITIAL or CHANGED")


def _validate_constraints(
    value: object,
    *,
    supported_kinds: Collection[RetrievalConstraintKindV1],
    validated_resource_refs: Collection[str] | None,
    validated_container_refs: Collection[str] | None,
    allow_empty: bool = False,
) -> list[SemanticRetrievalConstraintV1]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise RetrievalV2ValidationError("constraints must be non-empty")
    constraints = [
        _validate_constraint(
            item,
            supported_kinds=supported_kinds,
            validated_resource_refs=validated_resource_refs,
            validated_container_refs=validated_container_refs,
        )
        for item in value
    ]
    if len({constraint["kind"] for constraint in constraints}) != len(constraints):
        raise RetrievalV2ValidationError("effective constraints cannot duplicate a kind")
    return constraints


def _validate_constraint(
    value: object,
    *,
    supported_kinds: Collection[RetrievalConstraintKindV1],
    validated_resource_refs: Collection[str] | None,
    validated_container_refs: Collection[str] | None,
) -> SemanticRetrievalConstraintV1:
    constraint = _mapping(value, "constraint")
    if _FORBIDDEN_AUTHORITY_FIELDS.intersection(constraint):
        raise RetrievalV2ValidationError("semantic constraint contains execution authority")
    kind = constraint.get("kind")
    if kind not in _KINDS or kind not in supported_kinds:
        raise RetrievalV2ValidationError("constraint kind is unsupported for route")
    if kind == "TEMPORAL_RANGE":
        _exact_keys(
            constraint, {"kind", "axis", "start_local", "end_local", "timezone"}, "constraint"
        )
        return _validate_temporal(constraint)
    if kind == "PARTICIPANT":
        _exact_keys(constraint, {"kind", "participants", "match_mode"}, "constraint")
        participants = constraint["participants"]
        if not isinstance(participants, list) or not participants:
            raise RetrievalV2ValidationError("participants must be non-empty")
        validated = []
        for participant in participants:
            item = _mapping(participant, "participant")
            _exact_keys(item, {"role", "identity"}, "participant")
            if item["role"] not in {"ANY", "SENDER", "RECIPIENT", "ATTENDEE"} or not _string(
                item["identity"]
            ):
                raise RetrievalV2ValidationError("participant is invalid")
            validated.append(cast(ParticipantMatchV1, item))
        if constraint["match_mode"] not in {"ANY", "ALL"}:
            raise RetrievalV2ValidationError("participant match_mode is invalid")
        return {
            "kind": "PARTICIPANT",
            "participants": validated,
            "match_mode": cast(Literal["ANY", "ALL"], constraint["match_mode"]),
        }
    if kind == "KEYWORD":
        _exact_keys(constraint, {"kind", "terms", "match_mode"}, "constraint")
        if not _non_empty_strings(constraint["terms"]) or constraint["match_mode"] not in {
            "ANY",
            "ALL",
            "PHRASE",
        }:
            raise RetrievalV2ValidationError("keyword constraint is invalid")
        return {
            "kind": "KEYWORD",
            "terms": cast(list[str], constraint["terms"]),
            "match_mode": cast(Literal["ANY", "ALL", "PHRASE"], constraint["match_mode"]),
        }
    if kind == "RESOURCE_REF":
        _exact_keys(constraint, {"kind", "resource_refs"}, "constraint")
        refs = constraint["resource_refs"]
        ref_values = cast(list[str], refs)
        if (
            not _non_empty_strings(refs)
            or validated_resource_refs is None
            or not set(ref_values).issubset(validated_resource_refs)
        ):
            raise RetrievalV2ValidationError("resource refs must be validated for route")
        return {"kind": "RESOURCE_REF", "resource_refs": ref_values}
    if kind == "CONTAINER_REF":
        _exact_keys(constraint, {"kind", "container_refs"}, "constraint")
        refs = constraint["container_refs"]
        ref_values = cast(list[str], refs)
        if (
            not _non_empty_strings(refs)
            or validated_container_refs is None
            or not set(ref_values).issubset(validated_container_refs)
        ):
            raise RetrievalV2ValidationError("container refs must be validated for route")
        return {"kind": "CONTAINER_REF", "container_refs": ref_values}
    _exact_keys(constraint, {"kind", "values"}, "constraint")
    values = constraint["values"]
    allowed_values = {
        "ANY",
        "INCOMPLETE",
        "COMPLETED",
        "DRAFT",
        "SENT",
        "CANCELLED",
        "CONFIRMED",
        "TENTATIVE",
    }
    if not isinstance(values, list) or not values:
        raise RetrievalV2ValidationError("status scope is invalid")
    status_values = cast(list[str], values)
    if not set(status_values).issubset(allowed_values):
        raise RetrievalV2ValidationError("status scope is invalid")
    return {"kind": "STATUS_SCOPE", "values": cast(list[StatusScopeValueV1], status_values)}


def _validate_temporal(value: Mapping[str, object]) -> TemporalRangeConstraintV1:
    axis = value["axis"]
    start = value["start_local"]
    end = value["end_local"]
    timezone = value["timezone"]
    if axis not in {"MESSAGE_TIME", "TASK_SCHEDULED_DATE", "EVENT_TIME", "AVAILABILITY_WINDOW"}:
        raise RetrievalV2ValidationError("temporal axis is invalid")
    if start is not None and not _local_iso(start) or end is not None and not _local_iso(end):
        raise RetrievalV2ValidationError("temporal values must be offset-free local ISO")
    if start is None and end is None:
        raise RetrievalV2ValidationError("temporal range requires a boundary")
    if not _string(timezone):
        raise RetrievalV2ValidationError("temporal timezone is required")
    timezone_value = cast(str, timezone)
    try:
        ZoneInfo(timezone_value)
    except ZoneInfoNotFoundError as error:
        raise RetrievalV2ValidationError("temporal timezone is invalid") from error
    start_value = cast(str | None, start)
    end_value = cast(str | None, end)
    if (
        start_value is not None
        and end_value is not None
        and _parse_local(start_value) > _parse_local(end_value)
    ):
        raise RetrievalV2ValidationError("temporal range is reversed")
    return {
        "kind": "TEMPORAL_RANGE",
        "axis": cast(TemporalAxisV1, axis),
        "start_local": start_value,
        "end_local": end_value,
        "timezone": timezone_value,
    }


def _route_map(routes: Sequence[InputToolRouteV1]) -> dict[str, InputToolRouteV1]:
    result = {route["route_id"]: route for route in routes}
    if len(result) != len(routes):
        raise RetrievalV2ValidationError("frozen routes contain duplicate ids")
    return result


def _mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RetrievalV2ValidationError(f"{path} must be an object")
    return cast(dict[str, object], value)


def _exact_keys(value: Mapping[str, object], expected: set[str], path: str) -> None:
    if set(value) != expected:
        raise RetrievalV2ValidationError(f"{path} fields are invalid")


def _non_empty_strings(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(_string(item) for item in value)


def _string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _local_iso(value: object) -> bool:
    if not _string(value):
        return False
    text = cast(str, value)
    if text.endswith("Z"):
        return False
    try:
        return _parse_local(text).tzinfo is None
    except ValueError:
        return False


def _parse_local(value: str) -> datetime:
    if "T" not in value:
        return datetime.fromisoformat(f"{value}T00:00:00")
    return datetime.fromisoformat(value)
