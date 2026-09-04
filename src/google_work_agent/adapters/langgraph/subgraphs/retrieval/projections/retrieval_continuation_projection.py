"""Checkpoint-safe Retrieval continuation projection for Main back-edges."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict, cast

from google_work_agent.application.agents.retrieval.contracts.query_attempt import (
    QueryAttemptV1,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    SourceFetchPlanV1,
)


class RetrievalContinuationProjectionV1(TypedDict):
    canonical_plans: dict[str, SourceFetchPlanV1]
    query_attempts: list[QueryAttemptV1]
    read_result_handles: list[str]
    read_bindings: dict[str, dict[str, str]]
    segment_handles: list[str]


_FIELDS = (
    "__context_canonical_plans__",
    "__context_query_attempts__",
    "__context_read_result_handles__",
    "__context_read_bindings__",
    "__context_segment_handles__",
)


def restore_retrieval_continuation(
    state: Mapping[str, object], *, has_prior_result: bool
) -> RetrievalContinuationProjectionV1:
    """Restore one bounded continuation or use an old-checkpoint fresh-read fallback."""

    empty = RetrievalContinuationProjectionV1(
        canonical_plans={},
        query_attempts=[],
        read_result_handles=[],
        read_bindings={},
        segment_handles=[],
    )
    if not has_prior_result:
        return empty
    present = [field in state for field in _FIELDS]
    if not any(present):
        # Pre-cut-over checkpoints cannot safely materialize CHANGED. Their
        # caller performs one bounded fresh initial read from frozen facts.
        return empty
    if not all(present):
        raise ValueError("retrieval continuation checkpoint is incomplete")

    canonical_plans = state["__context_canonical_plans__"]
    query_attempts = state["__context_query_attempts__"]
    handles = state["__context_read_result_handles__"]
    bindings = state["__context_read_bindings__"]
    segment_handles = state["__context_segment_handles__"]
    if (
        not isinstance(canonical_plans, Mapping)
        or not isinstance(query_attempts, list)
        or not isinstance(handles, list)
        or not isinstance(bindings, Mapping)
        or not isinstance(segment_handles, list)
    ):
        raise ValueError("retrieval continuation checkpoint has invalid field types")
    if not all(isinstance(item, str) and item for item in handles + segment_handles):
        raise ValueError("retrieval continuation handles must be non-empty strings")
    if not all(isinstance(item, Mapping) for item in query_attempts):
        raise ValueError("retrieval continuation query attempts are malformed")

    typed_plans: dict[str, SourceFetchPlanV1] = {}
    for route_id, plan in canonical_plans.items():
        if (
            not isinstance(route_id, str)
            or not route_id
            or not isinstance(plan, Mapping)
            or plan.get("route_id") != route_id
        ):
            raise ValueError("retrieval continuation canonical plan is malformed")
        typed_plans[route_id] = cast(SourceFetchPlanV1, dict(plan))

    typed_bindings: dict[str, dict[str, str]] = {}
    for handle in handles:
        binding = bindings.get(handle)
        if not isinstance(binding, Mapping):
            raise ValueError("retrieval continuation handle is missing its binding")
        route_id = binding.get("route_id")
        query_hash = binding.get("query_identity_hash")
        if (
            not isinstance(route_id, str)
            or route_id not in typed_plans
            or not isinstance(query_hash, str)
            or not query_hash
        ):
            raise ValueError("retrieval continuation binding is malformed")
        typed_bindings[handle] = {
            "route_id": route_id,
            "query_identity_hash": query_hash,
        }

    return RetrievalContinuationProjectionV1(
        canonical_plans=typed_plans,
        query_attempts=cast(list[QueryAttemptV1], [dict(item) for item in query_attempts]),
        read_result_handles=list(cast(list[str], handles)),
        read_bindings=typed_bindings,
        segment_handles=list(cast(list[str], segment_handles)),
    )


__all__ = ["RetrievalContinuationProjectionV1", "restore_retrieval_continuation"]
