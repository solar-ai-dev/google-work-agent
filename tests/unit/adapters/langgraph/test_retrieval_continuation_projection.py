from typing import cast

import pytest

from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections import (
    retrieval_continuation_projection,
)
from google_work_agent.application.agents.retrieval.contracts.query_attempt import (
    QueryAttemptV1,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    SourceFetchPlanV1,
)


def test_restore_retrieval_continuation__preserves_bounded_prior_query() -> None:
    plan = cast(
        SourceFetchPlanV1,
        {
            "schema_version": 1,
            "route_id": "route-1",
            "connector_id": "google_workspace",
            "resource_type": "EMAIL",
            "operation_kind": "SEARCH",
            "effective_constraints": [
                {"kind": "KEYWORD", "terms": ["status"], "match_mode": "ANY"}
            ],
            "query_identity_hash": "a" * 64,
            "prior_read_result_handle": None,
            "detail_candidate_ref": None,
        },
    )
    attempt = cast(QueryAttemptV1, {"route_id": "route-1"})

    result = retrieval_continuation_projection.restore_retrieval_continuation(
        {
            "__context_canonical_plans__": {"route-1": plan},
            "__context_query_attempts__": [attempt],
            "__context_read_result_handles__": ["read-1"],
            "__context_read_bindings__": {
                "read-1": {
                    "route_id": "route-1",
                    "query_identity_hash": "a" * 64,
                }
            },
            "__context_segment_handles__": ["email:1"],
        },
        has_prior_result=True,
    )

    assert result["canonical_plans"] == {"route-1": plan}
    assert result["query_attempts"] == [attempt]
    assert result["read_result_handles"] == ["read-1"]


def test_restore_retrieval_continuation__old_checkpoint_uses_fresh_read() -> None:
    assert retrieval_continuation_projection.restore_retrieval_continuation(
        {}, has_prior_result=True
    ) == {
        "canonical_plans": {},
        "query_attempts": [],
        "read_result_handles": [],
        "read_bindings": {},
        "segment_handles": [],
    }


def test_restore_retrieval_continuation__rejects_partial_checkpoint() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        retrieval_continuation_projection.restore_retrieval_continuation(
            {"__context_canonical_plans__": {}},
            has_prior_result=True,
        )
