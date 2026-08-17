"""G3 Final Closure: retrieval.plan_query SEMANTIC_REVISION dedup.

RetrievalQueryPlannerAgent has no other dedicated unit test file (it is
otherwise exercised only through the SIX_ROLE_BASELINE integration suite),
so this file covers only the RunBudgetV1 wiring this task adds: the
same-node/same-failure-signature dedup gate around ``_revise_plan_once``.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import pytest

from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows import (
    approve_semantic_revision,
    build_default_run_budget,
    build_semantic_failure_signature_v1,
)
from google_work_agent.application.workflows.retrieval_query_planner import (
    RetrievalQueryPlannerAgent,
)
from google_work_agent.application.workflows.retrieval_v2_contracts import (
    RetrievalV2ValidationError,
)
from google_work_agent.ports import (
    ActualRuntime,
    OutputSchemaDefinition,
    PromptReference,
    RequestedRuntimeMode,
    StructuredLLMResult,
)

_PROMPT_REF = PromptReference(
    prompt_bundle_version="test",
    prompt_id="retrieval.plan_query",
    prompt_version="v1",
    content_hash="hash",
    agent_role="context_retriever",
    subgraph_name="context",
    node_name="plan_query",
    node_state="INITIAL",
    purpose="plan_query",
    input_schema_version="v1",
    output_schema_version="v1",
)
_REVISION_PROMPT_REF = PromptReference(
    prompt_bundle_version="test",
    prompt_id="retrieval.plan_query.revise",
    prompt_version="v1",
    content_hash="hash",
    agent_role="context_retriever",
    subgraph_name="context",
    node_name="plan_query",
    node_state="SEMANTIC_REVISION",
    purpose="plan_query.revise",
    input_schema_version="v1",
    output_schema_version="v1",
)
_OUTPUT_SCHEMA = OutputSchemaDefinition(schema_version="retrieval-query-plan-v2", json_schema={})


@dataclass
class _FakeLLMRuntime:
    queued: deque[StructuredLLMResult] = field(default_factory=deque)
    calls: list[dict[str, object]] = field(default_factory=list)

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
        semantic_validate: Callable[[object], object] | None = None,
    ) -> StructuredLLMResult:
        del output_schema, semantic_validate
        self.calls.append({"prompt_id": prompt_ref.prompt_id, "prompt_input": dict(prompt_input)})
        return self.queued.popleft()


def _llm_result(payload: object) -> StructuredLLMResult:
    return StructuredLLMResult(
        structured_output=payload,
        provider="fake",
        model="fake-model",
        requested_mode=RequestedRuntimeMode.AUTO,
        actual_runtime=ActualRuntime.API_LLM,
        input_tokens=1,
        output_tokens=1,
        total_tokens=2,
        latency_ms=1,
        estimated_cost_usd=None,
        fallback_reason=None,
        structured_output_attempts=1,
        provider_request_id="req-1",
        safe_error_code=None,
    )


_INVALID_PLAN: dict[str, object] = {
    "schema_version": 2,
    "route_queries": [],  # fails "plan.route_queries must be non-empty" immediately
    "required_information": ["info"],
    "retrieval_order": [],
}


def test_plan_query_semantic_revision_dedup_blocks_second_occurrence_after_resume() -> None:
    """G3 Final Closure G/H/I: retrieval.plan_query's SEMANTIC_REVISION retry
    is deduped Run-wide via approve_semantic_revision. A retry_budget that
    already carries this node's failure signature -- exactly what a
    resumed/re-entered Run or a freshly recreated runtime reading the
    checkpointed retry_budget would have -- denies the revise attempt before
    any Provider call, even on the very first plan() invocation this
    process/runtime instance ever makes."""
    signature = build_semantic_failure_signature_v1(
        node_id="retrieval.plan_query",
        failure_reason_codes=["RETRIEVAL_QUERY_PLAN_SEMANTIC_INVALID"],
    )
    already_used_budget = approve_semantic_revision(
        build_default_run_budget(), signature=signature
    )["run_budget"]
    assert len(already_used_budget["semantic_revision_signatures_used"]) == 1

    runtime = _FakeLLMRuntime()
    runtime.queued.append(_llm_result(_INVALID_PLAN))
    agent = RetrievalQueryPlannerAgent(
        llm_runtime=runtime,
        prompt_ref=_PROMPT_REF,
        output_schema=_OUTPUT_SCHEMA,
        revision_prompt_ref=_REVISION_PROMPT_REF,
    )

    with pytest.raises(RetrievalV2ValidationError, match="same failure signature already used"):
        agent.plan(
            prompt_input={},
            trace_context=ObservabilityContext(run_id="run-1", llm_call_id="llm-1"),
            frozen_routes=[],
            route_policies={},
            retry_budget=already_used_budget,
        )

    # Only the initial call was made -- the revise attempt was denied before
    # any second Provider call.
    assert len(runtime.calls) == 1


def test_plan_query_semantic_revision_allowed_on_first_occurrence() -> None:
    """Sanity check for the dedup test above: a fresh budget (no prior
    signature) does let the bounded one revise attempt happen."""
    runtime = _FakeLLMRuntime()
    runtime.queued.append(_llm_result(_INVALID_PLAN))
    runtime.queued.append(_llm_result(_INVALID_PLAN))
    agent = RetrievalQueryPlannerAgent(
        llm_runtime=runtime,
        prompt_ref=_PROMPT_REF,
        output_schema=_OUTPUT_SCHEMA,
        revision_prompt_ref=_REVISION_PROMPT_REF,
    )

    with pytest.raises(RetrievalV2ValidationError, match="route_queries must be non-empty"):
        agent.plan(
            prompt_input={},
            trace_context=ObservabilityContext(run_id="run-1", llm_call_id="llm-1"),
            frozen_routes=[],
            route_policies={},
            retry_budget=build_default_run_budget(),
        )

    # Initial call + one bounded revise attempt, both consumed from the queue.
    assert len(runtime.calls) == 2
