from typing import cast

import pytest

from google_work_agent.application.orchestration.retrieval_v2_contracts import (
    RetrievalConstraintKindV1,
    RetrievalV2ValidationError,
)
from google_work_agent.application.orchestration.source_fetch_plan_builder import (
    QueryUnchangedAfterFailureError,
    RouteConstraintPolicy,
    SourceFetchPlanBuilder,
)
from google_work_agent.application.orchestration.tool_routing import InputToolRouteV1


def test_builder_materializes_deterministic_initial_search() -> None:
    builder = SourceFetchPlanBuilder()
    first = builder.build(_initial_plan(), frozen_routes=_routes(), route_policies=_policies())
    second = builder.build(_initial_plan(), frozen_routes=_routes(), route_policies=_policies())

    assert first == second
    assert first[0]["schema_version"] == 1
    assert first[0]["effective_constraints"][0]["kind"] == "KEYWORD"


def test_builder_merges_changed_search_and_protects_required_constraint() -> None:
    builder = SourceFetchPlanBuilder()
    prior = builder.build(_initial_plan(), frozen_routes=_routes(), route_policies=_policies())[0]
    changed = _changed_plan(
        upserts=[{"kind": "KEYWORD", "terms": ["renewal"], "match_mode": "PHRASE"}],
        removals=[],
    )

    result = builder.build(
        changed,
        frozen_routes=_routes(),
        route_policies=_policies(),
        prior_plans={"route-1": prior},
    )

    assert result[0]["effective_constraints"] == [
        {"kind": "KEYWORD", "terms": ["renewal"], "match_mode": "PHRASE"}
    ]
    assert result[0]["query_identity_hash"] != prior["query_identity_hash"]

    with pytest.raises(RetrievalV2ValidationError, match="required"):
        builder.build(
            _changed_plan(upserts=[], removals=["KEYWORD"]),
            frozen_routes=_routes(),
            route_policies=_policies(),
            prior_plans={"route-1": prior},
        )


def test_builder_rejects_same_kind_delta_conflict_and_unchanged_query() -> None:
    builder = SourceFetchPlanBuilder()
    prior = builder.build(_initial_plan(), frozen_routes=_routes(), route_policies=_policies())[0]

    with pytest.raises(RetrievalV2ValidationError, match="upserts and removes"):
        builder.build(
            _changed_plan(
                upserts=[{"kind": "KEYWORD", "terms": ["invoice"], "match_mode": "ANY"}],
                removals=["KEYWORD"],
            ),
            frozen_routes=_routes(),
            route_policies=_policies(),
            prior_plans={"route-1": prior},
        )
    with pytest.raises(QueryUnchangedAfterFailureError, match="QUERY_UNCHANGED_AFTER_FAILURE"):
        builder.build(
            _changed_plan(
                upserts=[{"kind": "KEYWORD", "terms": ["invoice"], "match_mode": "ANY"}],
                removals=[],
            ),
            frozen_routes=_routes(),
            route_policies=_policies(),
            prior_plans={"route-1": prior},
        )


@pytest.mark.parametrize(
    ("constraint", "supported", "validated_resource_refs", "validated_container_refs"),
    [
        (
            {
                "kind": "TEMPORAL_RANGE",
                "axis": "MESSAGE_TIME",
                "start_local": "2026-08-15T09:00:00",
                "end_local": "2026-08-15T10:00:00",
                "timezone": "Asia/Seoul",
            },
            frozenset({"TEMPORAL_RANGE"}),
            None,
            None,
        ),
        (
            {
                "kind": "PARTICIPANT",
                "participants": [{"role": "SENDER", "identity": "person-ref-1"}],
                "match_mode": "ANY",
            },
            frozenset({"PARTICIPANT"}),
            None,
            None,
        ),
        (
            {"kind": "KEYWORD", "terms": ["invoice"], "match_mode": "ANY"},
            frozenset({"KEYWORD"}),
            None,
            None,
        ),
        (
            {"kind": "RESOURCE_REF", "resource_refs": ["resource-ref-1"]},
            frozenset({"RESOURCE_REF"}),
            {"route-1": {"resource-ref-1"}},
            None,
        ),
        (
            {"kind": "CONTAINER_REF", "container_refs": ["container-ref-1"]},
            frozenset({"CONTAINER_REF"}),
            None,
            {"route-1": {"container-ref-1"}},
        ),
        (
            {"kind": "STATUS_SCOPE", "values": ["ANY"]},
            frozenset({"STATUS_SCOPE"}),
            None,
            None,
        ),
    ],
)
def test_builder_accepts_each_semantic_constraint_variant(
    constraint: dict[str, object],
    supported: frozenset[str],
    validated_resource_refs: dict[str, set[str]] | None,
    validated_container_refs: dict[str, set[str]] | None,
) -> None:
    result = SourceFetchPlanBuilder().build(
        _initial_plan(constraints=[constraint]),
        frozen_routes=_routes(),
        route_policies=_policies(supported=supported, required=supported),
        validated_resource_refs=validated_resource_refs,
        validated_container_refs=validated_container_refs,
    )

    assert result[0]["effective_constraints"] == [constraint]


@pytest.mark.parametrize(
    "constraint",
    [
        {"kind": "UNKNOWN", "value": "x"},
        {"kind": "KEYWORD", "terms": [], "match_mode": "ANY"},
        {
            "kind": "TEMPORAL_RANGE",
            "axis": "MESSAGE_TIME",
            "start_local": "2026-08-15T10:00:00",
            "end_local": "2026-08-15T09:00:00",
            "timezone": "Asia/Seoul",
        },
        {
            "kind": "TEMPORAL_RANGE",
            "axis": "MESSAGE_TIME",
            "start_local": "2026-08-15T10:00:00Z",
            "end_local": None,
            "timezone": "Asia/Seoul",
        },
        {"kind": "KEYWORD", "terms": ["invoice"], "match_mode": "ANY", "provider_query": "from:a"},
    ],
)
def test_builder_fails_closed_for_invalid_or_execution_authority_constraint(
    constraint: dict[str, object],
) -> None:
    with pytest.raises(RetrievalV2ValidationError):
        SourceFetchPlanBuilder().build(
            _initial_plan(constraints=[constraint]),
            frozen_routes=_routes(),
            route_policies=_policies(supported=frozenset({"KEYWORD", "TEMPORAL_RANGE"})),
        )


def test_builder_rejects_unvalidated_refs_and_next_page_without_handle() -> None:
    builder = SourceFetchPlanBuilder()
    with pytest.raises(RetrievalV2ValidationError, match="resource refs"):
        builder.build(
            _initial_plan(
                constraints=[{"kind": "RESOURCE_REF", "resource_refs": ["raw-provider-id"]}]
            ),
            frozen_routes=_routes(),
            route_policies=_policies(supported=frozenset({"RESOURCE_REF"}), required=frozenset()),
        )
    with pytest.raises(RetrievalV2ValidationError, match="prior read-result handle"):
        builder.build(_next_page_plan(), frozen_routes=_routes(), route_policies=_policies())


def _routes() -> list[InputToolRouteV1]:
    return [
        {
            "route_id": "route-1",
            "connector_id": "google_workspace",
            "resource_type": "EMAIL",
            "allowed_read_tool_ids": ["gmail_search_messages"],
            "required": True,
            "reason_codes": ["MISSING_INVOICE"],
        }
    ]


def _policies(
    *,
    supported: frozenset[str] = frozenset({"KEYWORD"}),
    required: frozenset[str] = frozenset({"KEYWORD"}),
) -> dict[str, RouteConstraintPolicy]:
    return {
        "route-1": RouteConstraintPolicy(
            supported_kinds=cast(frozenset[RetrievalConstraintKindV1], supported),
            required_kinds=cast(frozenset[RetrievalConstraintKindV1], required),
        )
    }


def _initial_plan(*, constraints: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "SEARCH",
                "reason_codes": ["MISSING_INVOICE"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": constraints
                    or [{"kind": "KEYWORD", "terms": ["invoice"], "match_mode": "ANY"}],
                },
                "detail_candidate_ref": None,
            }
        ],
        "required_information": ["invoice"],
        "retrieval_order": ["route-1"],
    }


def _changed_plan(*, upserts: list[dict[str, object]], removals: list[str]) -> dict[str, object]:
    return {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "SEARCH",
                "reason_codes": ["MISSING_INVOICE"],
                "search_spec": {
                    "mode": "CHANGED",
                    "constraint_delta": {
                        "upsert_constraints": upserts,
                        "remove_constraint_kinds": removals,
                    },
                },
                "detail_candidate_ref": None,
            }
        ],
        "required_information": ["invoice"],
        "retrieval_order": ["route-1"],
    }


def _next_page_plan() -> dict[str, object]:
    return {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "NEXT_PAGE",
                "reason_codes": ["MISSING_INVOICE"],
                "search_spec": None,
                "detail_candidate_ref": None,
            }
        ],
        "required_information": ["invoice"],
        "retrieval_order": ["route-1"],
    }
