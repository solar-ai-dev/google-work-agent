"""Compatibility delegate to the canonical Retrieval planner operation."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from google_work_agent.application.agents.retrieval.build_query import RouteConstraintPolicy
from google_work_agent.application.agents.retrieval.plan_query import plan_query
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.orchestration.retrieval_v2_contracts import (
    RetrievalQueryPlanV2,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    RunBudgetV2,
)
from google_work_agent.ports.llm import OutputSchemaDefinition, PromptReference
from google_work_agent.ports.system.contracts.observability import ObservabilityContext


def load_retrieval_plan_query_revision_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return load_prompt_reference(
        "retrieval.plan_query.revise", manifest_path or default_prompt_manifest_path()
    )


class RetrievalQueryPlannerAgent:
    """Temporary #114-facing facade; owns no planning semantics."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredLLMRuntime,
        prompt_ref: PromptReference,
        output_schema: OutputSchemaDefinition,
        revision_prompt_ref: PromptReference | None = None,
        manifest_path: Path | None = None,
    ) -> None:
        self._llm_runtime = llm_runtime
        self._prompt_ref = prompt_ref
        self._output_schema = output_schema
        self._revision_prompt_ref = revision_prompt_ref or (
            load_retrieval_plan_query_revision_prompt_reference(manifest_path)
        )

    def plan(
        self,
        *,
        prompt_input: dict[str, object],
        trace_context: ObservabilityContext,
        frozen_routes: Sequence[InputToolRouteV1],
        route_policies: Mapping[str, RouteConstraintPolicy],
        retry_budget: RunBudgetV2,
        validated_resource_refs: Mapping[str, Collection[str]] | None = None,
        validated_container_refs: Mapping[str, Collection[str]] | None = None,
        detail_candidate_refs: Collection[str] = (),
    ) -> tuple[RetrievalQueryPlanV2, RunBudgetV2]:
        return plan_query(
            llm_runtime=self._llm_runtime,
            prompt_ref=self._prompt_ref,
            revision_prompt_ref=self._revision_prompt_ref,
            output_schema=self._output_schema,
            prompt_input=prompt_input,
            trace_context=trace_context,
            frozen_routes=frozen_routes,
            route_policies=route_policies,
            retry_budget=retry_budget,
            validated_resource_refs=validated_resource_refs,
            validated_container_refs=validated_container_refs,
            detail_candidate_refs=detail_candidate_refs,
        )


__all__ = [
    "RetrievalQueryPlannerAgent",
    "load_retrieval_plan_query_revision_prompt_reference",
]
