"""Canonical Retrieval semantic operation: plan_query."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

from google_work_agent.application.agents.retrieval.build_query import RouteConstraintPolicy
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.orchestration.failure_record import build_failure_record_v1
from google_work_agent.application.orchestration.retrieval_v2_contracts import (
    RetrievalConstraintKindV1,
    RetrievalQueryPlanV2,
    RetrievalV2ValidationError,
    validate_retrieval_query_plan_v2,
)
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    BudgetDecision,
    RunBudgetV2,
    approve_semantic_revision,
    build_semantic_failure_signature_v1,
)
from google_work_agent.ports.llm import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.system.contracts.observability import ObservabilityContext


def plan_query(
    *,
    llm_runtime: StructuredLLMRuntime,
    prompt_ref: PromptReference,
    revision_prompt_ref: PromptReference,
    output_schema: OutputSchemaDefinition,
    prompt_input: dict[str, object],
    trace_context: ObservabilityContext,
    frozen_routes: Sequence[InputToolRouteV1],
    route_policies: Mapping[str, RouteConstraintPolicy],
    retry_budget: RunBudgetV2,
    validated_resource_refs: Mapping[str, Collection[str]] | None = None,
    validated_container_refs: Mapping[str, Collection[str]] | None = None,
    detail_candidate_refs: Collection[str] = (),
) -> tuple[RetrievalQueryPlanV2, RunBudgetV2]:
    """Plan provider-neutral retrieval intent against already-frozen input routes."""
    supported_kinds: dict[str, frozenset[RetrievalConstraintKindV1]] = {
        route_id: policy.supported_kinds for route_id, policy in route_policies.items()
    }
    result = llm_runtime.invoke_structured(
        prompt_ref=prompt_ref,
        prompt_input=prompt_input,
        output_schema=output_schema,
        trace_context=trace_context,
    )
    try:
        return (
            validate_retrieval_query_plan_v2(
                result.structured_output,
                frozen_routes=frozen_routes,
                supported_constraint_kinds=supported_kinds,
                validated_resource_refs=validated_resource_refs,
                validated_container_refs=validated_container_refs,
                detail_candidate_refs=detail_candidate_refs,
            ),
            retry_budget,
        )
    except RetrievalV2ValidationError as error:
        return _revise_plan_once(
            llm_runtime=llm_runtime,
            revision_prompt_ref=revision_prompt_ref,
            output_schema=output_schema,
            prompt_input=prompt_input,
            trace_context=trace_context,
            frozen_routes=frozen_routes,
            supported_kinds=supported_kinds,
            validated_resource_refs=validated_resource_refs,
            validated_container_refs=validated_container_refs,
            detail_candidate_refs=detail_candidate_refs,
            previous_output=result.structured_output,
            failure_detail=str(error),
            retry_budget=retry_budget,
        )


def _revise_plan_once(
    *,
    llm_runtime: StructuredLLMRuntime,
    revision_prompt_ref: PromptReference,
    output_schema: OutputSchemaDefinition,
    prompt_input: dict[str, object],
    trace_context: ObservabilityContext,
    frozen_routes: Sequence[InputToolRouteV1],
    supported_kinds: Mapping[str, frozenset[RetrievalConstraintKindV1]],
    validated_resource_refs: Mapping[str, Collection[str]] | None,
    validated_container_refs: Mapping[str, Collection[str]] | None,
    detail_candidate_refs: Collection[str],
    previous_output: object,
    failure_detail: str,
    retry_budget: RunBudgetV2,
) -> tuple[RetrievalQueryPlanV2, RunBudgetV2]:
    failure_code = "RETRIEVAL_QUERY_PLAN_SEMANTIC_INVALID"
    signature = build_semantic_failure_signature_v1(
        node_id="retrieval.plan_query",
        failure_reason_codes=[failure_code],
    )
    decision = approve_semantic_revision(retry_budget, signature=signature)
    if decision["decision"] == BudgetDecision.DENY.value:
        raise RetrievalV2ValidationError(
            "retrieval query plan revision denied: same failure signature already used"
        )
    revision = llm_runtime.invoke_structured(
        prompt_ref=revision_prompt_ref,
        prompt_input={
            "base_projection": dict(prompt_input),
            "candidate_output": previous_output,
            "failure_record": build_failure_record_v1(
                failure_reason_code=failure_code,
                failure_origin="QUERY_PLANNING",
                detected_by="RUNTIME_DOMAIN_VALIDATOR",
                runtime_disposition="RETRYABLE",
                experiment_disposition="RUN_REVISION",
                affected_field_paths=[
                    "$.route_queries",
                    "$.required_information",
                    "$.retrieval_order",
                ],
                failure_context_ids=[failure_detail],
            ),
        },
        output_schema=output_schema,
        trace_context=trace_context,
    )
    return (
        validate_retrieval_query_plan_v2(
            revision.structured_output,
            frozen_routes=frozen_routes,
            supported_constraint_kinds=supported_kinds,
            validated_resource_refs=validated_resource_refs,
            validated_container_refs=validated_container_refs,
            detail_candidate_refs=detail_candidate_refs,
        ),
        decision["run_budget"],
    )
