"""LLM boundary for the canonical RetrievalQueryPlanV2 contract."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.orchestration.contracts import (
    BudgetDecision,
    RunBudgetV1,
    approve_semantic_revision,
    build_semantic_failure_signature_v1,
)
from google_work_agent.application.orchestration.failure_record import build_failure_record_v1
from google_work_agent.application.orchestration.retrieval_v2_contracts import (
    RetrievalConstraintKindV1,
    RetrievalQueryPlanV2,
    RetrievalV2ValidationError,
    validate_retrieval_query_plan_v2,
)
from google_work_agent.application.orchestration.source_fetch_plan_builder import (
    RouteConstraintPolicy,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path as _registry_default_prompt_manifest_path,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    load_prompt_reference as _load_registry_prompt_reference,
)
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.ports.events.observability_events import ObservabilityContext
from google_work_agent.ports.llm import (
    OutputSchemaDefinition,
    PromptReference,
)


def load_retrieval_plan_query_revision_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "retrieval.plan_query.revise",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


class RetrievalQueryPlannerAgent:
    """Invoke the planner LLM for semantic intent only; never build or execute reads."""

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
        self._revision_prompt_ref = (
            revision_prompt_ref
            or load_retrieval_plan_query_revision_prompt_reference(manifest_path)
        )

    def plan(
        self,
        *,
        prompt_input: dict[str, object],
        trace_context: ObservabilityContext,
        frozen_routes: Sequence[InputToolRouteV1],
        route_policies: Mapping[str, RouteConstraintPolicy],
        retry_budget: RunBudgetV1,
        validated_resource_refs: Mapping[str, Collection[str]] | None = None,
        validated_container_refs: Mapping[str, Collection[str]] | None = None,
        detail_candidate_refs: Collection[str] = (),
    ) -> tuple[RetrievalQueryPlanV2, RunBudgetV1]:
        """Return a fail-closed, provider-neutral V2 retrieval plan."""
        supported_kinds: dict[str, frozenset[RetrievalConstraintKindV1]] = {
            route_id: policy.supported_kinds for route_id, policy in route_policies.items()
        }
        result = self._llm_runtime.invoke_structured(
            prompt_ref=self._prompt_ref,
            prompt_input=prompt_input,
            output_schema=self._output_schema,
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
            return self._revise_plan_once(
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
        self,
        *,
        prompt_input: dict[str, object],
        trace_context: ObservabilityContext,
        frozen_routes: Sequence[InputToolRouteV1],
        supported_kinds: Mapping[str, frozenset[RetrievalConstraintKindV1]],
        validated_resource_refs: Mapping[str, Collection[str]] | None,
        validated_container_refs: Mapping[str, Collection[str]] | None,
        detail_candidate_refs: Collection[str],
        previous_output: object,
        failure_detail: str,
        retry_budget: RunBudgetV1,
    ) -> tuple[RetrievalQueryPlanV2, RunBudgetV1]:
        """Bounded SEMANTIC_REVISION retry (max 1 per Node/Failure Signature):
        a schema-shaped plan that fails RetrievalQueryPlanV2's own semantic
        checks (frozen-route/constraint-policy/validated-ref violations) gets
        one re-grounding attempt against the dedicated .revise prompt --
        never the generic SCHEMA_REPAIR path. If the revision also fails,
        the error propagates to the caller's existing fail-closed handling.

        G3: dedup via approve_semantic_revision -- a second occurrence of the
        same normalized failure signature for this node, anywhere in the Run
        (including after resume/checkpoint restore), is denied before any
        Provider call and raises the same RetrievalV2ValidationError a failed
        revision attempt would."""
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
        mutable_fields = ["$.route_queries", "$.required_information", "$.retrieval_order"]
        revision_result = self._llm_runtime.invoke_structured(
            prompt_ref=self._revision_prompt_ref,
            prompt_input={
                "base_projection": dict(prompt_input),
                "candidate_output": previous_output,
                "failure_record": build_failure_record_v1(
                    failure_reason_code=failure_code,
                    failure_origin="QUERY_PLANNING",
                    detected_by="RUNTIME_DOMAIN_VALIDATOR",
                    runtime_disposition="RETRYABLE",
                    experiment_disposition="RUN_REVISION",
                    affected_field_paths=mutable_fields,
                    failure_context_ids=[failure_detail],
                ),
            },
            output_schema=self._output_schema,
            trace_context=trace_context,
        )
        return (
            validate_retrieval_query_plan_v2(
                revision_result.structured_output,
                frozen_routes=frozen_routes,
                supported_constraint_kinds=supported_kinds,
                validated_resource_refs=validated_resource_refs,
                validated_container_refs=validated_container_refs,
                detail_candidate_refs=detail_candidate_refs,
            ),
            decision["run_budget"],
        )
