from collections.abc import Collection, Mapping, Sequence
from typing import NotRequired, TypedDict, cast

from google_work_agent.application.agents.retrieval.build_query import RouteConstraintPolicy
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.orchestration.retrieval_v2_contracts import SourceFetchPlanV1


class BuildQueryInput(TypedDict):
    plan: object
    frozen_routes: Sequence[InputToolRouteV1]
    route_policies: Mapping[str, RouteConstraintPolicy]
    prior_plans: NotRequired[Mapping[str, SourceFetchPlanV1] | None]
    prior_read_result_handles: NotRequired[Mapping[str, str] | None]
    validated_resource_refs: NotRequired[Mapping[str, Collection[str]] | None]
    validated_container_refs: NotRequired[Mapping[str, Collection[str]] | None]
    detail_candidate_refs: NotRequired[Collection[str]]


def project_build_query_input(state: Mapping[str, object]) -> BuildQueryInput:
    inputs = state.get("operation_inputs")
    value = inputs.get("build_query") if isinstance(inputs, Mapping) else None
    if not isinstance(value, Mapping):
        raise ValueError("missing typed input projection for retrieval.build_query")
    return cast(BuildQueryInput, dict(value))
