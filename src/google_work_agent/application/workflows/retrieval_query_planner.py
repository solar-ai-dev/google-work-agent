"""LLM boundary for the canonical RetrievalQueryPlanV2 contract."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

from google_work_agent.application.llm import StructuredLLMRuntime
from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows.retrieval_v2_contracts import (
    RetrievalConstraintKindV1,
    RetrievalQueryPlanV2,
    validate_retrieval_query_plan_v2,
)
from google_work_agent.application.workflows.source_fetch_plan_builder import RouteConstraintPolicy
from google_work_agent.application.workflows.tool_routing import InputToolRouteV1
from google_work_agent.ports import OutputSchemaDefinition, PromptReference


class RetrievalQueryPlannerAgent:
    """Invoke the planner LLM for semantic intent only; never build or execute reads."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredLLMRuntime,
        prompt_ref: PromptReference,
        output_schema: OutputSchemaDefinition,
    ) -> None:
        self._llm_runtime = llm_runtime
        self._prompt_ref = prompt_ref
        self._output_schema = output_schema

    def plan(
        self,
        *,
        prompt_input: dict[str, object],
        trace_context: ObservabilityContext,
        frozen_routes: Sequence[InputToolRouteV1],
        route_policies: Mapping[str, RouteConstraintPolicy],
        validated_resource_refs: Mapping[str, Collection[str]] | None = None,
        validated_container_refs: Mapping[str, Collection[str]] | None = None,
        detail_candidate_refs: Collection[str] = (),
    ) -> RetrievalQueryPlanV2:
        """Return a fail-closed, provider-neutral V2 retrieval plan."""
        supported_kinds: dict[str, frozenset[RetrievalConstraintKindV1]] = {
            route_id: policy.supported_kinds for route_id, policy in route_policies.items()
        }
        result = self._llm_runtime.invoke_structured(
            prompt_ref=self._prompt_ref,
            prompt_input=prompt_input,
            output_schema=self._output_schema,
            trace_context=trace_context,
            semantic_validate=lambda value: validate_retrieval_query_plan_v2(
                value,
                frozen_routes=frozen_routes,
                supported_constraint_kinds=supported_kinds,
                validated_resource_refs=validated_resource_refs,
                validated_container_refs=validated_container_refs,
                detail_candidate_refs=detail_candidate_refs,
            ),
        )
        return validate_retrieval_query_plan_v2(
            result.structured_output,
            frozen_routes=frozen_routes,
            supported_constraint_kinds=supported_kinds,
            validated_resource_refs=validated_resource_refs,
            validated_container_refs=validated_container_refs,
            detail_candidate_refs=detail_candidate_refs,
        )
