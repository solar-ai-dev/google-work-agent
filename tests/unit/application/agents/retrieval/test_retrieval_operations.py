from __future__ import annotations

from typing import cast

import pytest

from google_work_agent.application.agents.retrieval.build_query import (
    QueryUnchangedAfterFailureError,
    RouteConstraintPolicy,
    build_query,
)
from google_work_agent.application.agents.retrieval.normalize_segments import (
    ContextBudget,
    SourceSegment,
    normalize_segments,
)
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import (
    rag_retrieve_rerank,
)
from google_work_agent.application.workflows.handoff_contracts import (
    AcquisitionResultV1,
    RequestIntentV2,
)
from google_work_agent.application.workflows.retrieval_v2_contracts import (
    RetrievalQueryPlanV2,
    SourceFetchPlanV1,
)
from google_work_agent.application.workflows.tool_routing import InputToolRouteV1


def _route() -> InputToolRouteV1:
    return {
        "route_id": "route-1",
        "connector_id": "google_workspace",
        "resource_type": "EMAIL",
        "allowed_read_tool_ids": ["gmail_search"],
        "required": True,
        "reason_codes": ["USER_REQUEST"],
    }


def test_build_query_preserves_frozen_connector_and_materializes_hash() -> None:
    plan = cast(RetrievalQueryPlanV2, {
        "schema_version": 2,
        "route_queries": [{
            "route_id": "route-1",
            "operation": "SEARCH",
            "reason_codes": ["USER_REQUEST"],
            "search_spec": {
                "mode": "INITIAL",
                "constraints": [{
                    "kind": "KEYWORD",
                    "terms": ["alpha"],
                    "match_mode": "ANY",
                }],
            },
            "detail_candidate_ref": None,
        }],
        "required_information": ["mail"],
        "retrieval_order": ["route-1"],
    })
    result = build_query(
        plan,
        frozen_routes=[_route()],
        route_policies={
            "route-1": RouteConstraintPolicy(
                supported_kinds=frozenset({"KEYWORD"}),
            )
        },
    )
    assert result[0]["connector_id"] == "google_workspace"
    assert result[0]["route_id"] == "route-1"
    assert len(result[0]["query_identity_hash"]) == 64


def test_build_query_rejects_unchanged_changed_search() -> None:
    prior = cast(SourceFetchPlanV1, {
        "schema_version": 1,
        "route_id": "route-1",
        "connector_id": "google_workspace",
        "resource_type": "EMAIL",
        "operation_kind": "SEARCH",
        "effective_constraints": [{
            "kind": "KEYWORD",
            "terms": ["alpha"],
            "match_mode": "ANY",
        }],
        "query_identity_hash": "a" * 64,
        "prior_read_result_handle": None,
        "detail_candidate_ref": None,
    })
    changed = cast(RetrievalQueryPlanV2, {
        "schema_version": 2,
        "route_queries": [{
            "route_id": "route-1",
            "operation": "SEARCH",
            "reason_codes": ["FOLLOW_UP"],
            "search_spec": {
                "mode": "CHANGED",
                "constraint_delta": {
                    "upsert_constraints": [{
                        "kind": "KEYWORD",
                        "terms": ["alpha"],
                        "match_mode": "ANY",
                    }],
                    "remove_constraint_kinds": [],
                },
            },
            "detail_candidate_ref": None,
        }],
        "required_information": ["mail"],
        "retrieval_order": ["route-1"],
    })
    with pytest.raises(QueryUnchangedAfterFailureError):
        build_query(
            changed,
            frozen_routes=[_route()],
            route_policies={
                "route-1": RouteConstraintPolicy(
                    supported_kinds=frozenset({"KEYWORD"}),
                )
            },
            prior_plans={"route-1": prior},
        )


def test_normalize_segments_strips_quoted_gmail_content_and_bounds_segments() -> None:
    acquisition = cast(AcquisitionResultV1, {
        "schema_version": 1,
        "source_summaries": [{
            "source": "GMAIL",
            "status": "COMPLETE",
            "resources": [{
                "resource_handle": "h1",
                "resource_type": "gmail_message",
                "resource_id": "m1",
                "payload": {"body": "current reply\n--\nsignature\n> quoted"},
            }],
        }],
        "resource_handles": ["h1"],
        "availability_results": [],
    })
    segments = normalize_segments(
        acquisition,
        context_budget=ContextBudget(max_segments=3, chunk_max_tokens=900),
    )
    assert len(segments) == 1
    assert segments[0].text == "current reply"


def test_rag_retrieve_rerank_forces_explicit_selected_resource() -> None:
    intent = cast(RequestIntentV2, {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "alpha",
        "constraints": [{"kind": "RESOURCE", "value": ["selected"]}],
        "requested_effect_hints": ["READ"],
    })
    segments = [
        SourceSegment(
            "seg-1", "h1", "GMAIL", "gmail_message", "other", None, None, {}, "alpha alpha"
        ),
        SourceSegment(
            "seg-2",
            "h2",
            "GMAIL",
            "gmail_message",
            "selected",
            None,
            None,
            {},
            "unrelated",
        ),
    ]
    ranked = rag_retrieve_rerank(segments, request_intent=intent, top_k=1)
    assert {item["segment_id"] for item in ranked} == {"seg-1", "seg-2"}
    assert "RESOURCE_SELECTED_FORCED" in ranked[1]["reason_codes"]
