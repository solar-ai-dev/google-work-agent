from collections.abc import Collection, Mapping, Sequence
from typing import NotRequired, TypedDict, cast

from google_work_agent.application.agents.retrieval.build_query import RouteConstraintPolicy
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    RunBudgetV2,
)
from google_work_agent.ports.llm import OutputSchemaDefinition, PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1


class PlanQueryInput(TypedDict):
    llm_runtime: StructuredInferencePort
    prompt_ref: PromptReference
    revision_prompt_ref: PromptReference
    output_schema: OutputSchemaDefinition
    prompt_input: dict[str, object]
    requested_mode: RequestedModeV1
    frozen_routes: Sequence[InputToolRouteV1]
    route_policies: Mapping[str, RouteConstraintPolicy]
    retry_budget: RunBudgetV2
    validated_resource_refs: NotRequired[Mapping[str, Collection[str]] | None]
    validated_container_refs: NotRequired[Mapping[str, Collection[str]] | None]
    detail_candidate_refs: NotRequired[Collection[str]]


def project_plan_query_input(state: Mapping[str, object]) -> PlanQueryInput:
    return cast(PlanQueryInput, _project(state, "plan_query"))


def _project(state: Mapping[str, object], operation: str) -> dict[str, object]:
    inputs = state.get("operation_inputs")
    value = inputs.get(operation) if isinstance(inputs, Mapping) else None
    if not isinstance(value, Mapping):
        raise ValueError(f"missing typed input projection for retrieval.{operation}")
    return dict(value)
