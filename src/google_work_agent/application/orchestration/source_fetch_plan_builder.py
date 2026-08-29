"""Compatibility delegate to the canonical Retrieval query builder."""

from collections.abc import Collection, Mapping, Sequence

from google_work_agent.application.agents.retrieval.build_query import (
    QueryUnchangedAfterFailureError,
    RouteConstraintPolicy,
    build_query,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.orchestration.retrieval_v2_contracts import SourceFetchPlanV1


class SourceFetchPlanBuilder:
    """Temporary #114-facing facade; owns no query-building semantics."""

    def build(
        self,
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
        return build_query(
            plan,
            frozen_routes=frozen_routes,
            route_policies=route_policies,
            prior_plans=prior_plans,
            prior_read_result_handles=prior_read_result_handles,
            validated_resource_refs=validated_resource_refs,
            validated_container_refs=validated_container_refs,
            detail_candidate_refs=detail_candidate_refs,
        )


__all__ = [
    "QueryUnchangedAfterFailureError",
    "RouteConstraintPolicy",
    "SourceFetchPlanBuilder",
]
