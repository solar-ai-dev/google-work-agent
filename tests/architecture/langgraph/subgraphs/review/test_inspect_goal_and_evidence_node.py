# ruff: noqa: E501
from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import cast

import pytest

from google_work_agent.adapters.langgraph.subgraphs.review.graph import (
    ReviewRuntimeDependencies,
    ReviewSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.review.nodes.inspect_goal_and_evidence_node import (
    inspect_goal_and_evidence_node,
)
from google_work_agent.adapters.langgraph.subgraphs.review.projections.inspect_goal_and_evidence_projection import (
    project_inspect_goal_and_evidence_input,
)
from google_work_agent.adapters.langgraph.subgraphs.review.routing.route_after_inspect_goal_and_evidence import (
    route_after_inspect_goal_and_evidence,
)
from google_work_agent.adapters.langgraph.subgraphs.review.runtime_active_graph import (
    RuntimeActiveReviewSubgraph,
)
from google_work_agent.application.orchestration.plan_review import PlanReviewAgent
from google_work_agent.application.prompt_runtime.prompt_registry import (
    InactivePromptArtifactError,
)
from google_work_agent.ports.llm import (
    ActualRuntime,
    RequestedRuntimeMode,
    StructuredLLMResult,
)

DIMENSION = "review.inspect_goal_and_evidence"


def test_goal_node_projection_and_answer_router_are_exact() -> None:
    state = {
        "request_intent": {},
        "planning_result": {"schema_version": 2, "answer": "draft"},
        "tool_route_plan": {"secret": "must not project"},
        "evidence": [],
    }
    assert set(project_inspect_goal_and_evidence_input(state)) == {
        "request_intent",
        "planning_result",
        "evidence",
    }
    patch = inspect_goal_and_evidence_node(
        state,
        invoke=lambda _prompt_id, _input: {
            "schema_version": 1,
            "dimension": DIMENSION,
            "findings": [],
        },
    )
    assert set(patch) == {"goal_evidence_result"}
    assert route_after_inspect_goal_and_evidence({**state, **patch}) == ("aggregate_findings")


def test_non_active_goal_prompt_fails_before_structured_inference() -> None:
    class FakeRuntime:
        calls = 0

        def invoke_structured(self, **_kwargs: object) -> object:
            self.calls += 1
            raise AssertionError("inactive Prompt must not reach StructuredInferencePort")

    runtime = FakeRuntime()
    graph = ReviewSubgraph(llm_runtime=runtime)  # type: ignore[arg-type]
    invoke = graph.semantic_invoker({"run_id": "run-1"})

    with pytest.raises(InactivePromptArtifactError, match="not activation-gate complete"):
        invoke(
            "review.inspect_goal_and_evidence",
            {"request_intent": {}, "planning_result": {}, "evidence": []},
        )
    assert runtime.calls == 0


def test_production_inspection_has_no_broad_plan_review_semantic_caller() -> None:
    source = inspect.getsource(RuntimeActiveReviewSubgraph._run_atomic_inspection)
    assert "inspect_goal_and_evidence_node" in source
    assert "inspect_action_scope_and_route_node" in source
    assert "inspect_constraints_and_policy_summary_node" in source
    assert "invoke_inspect_llm" not in source
    assert not hasattr(PlanReviewAgent, "invoke_inspect_llm_from_evidence")


def test_review_graph_uses_exact_atomic_runtime_node_ids() -> None:
    graph = ReviewSubgraph(
        dependencies=ReviewRuntimeDependencies(
            invoke=lambda _prompt_id, _input: {
                "schema_version": 1,
                "dimension": DIMENSION,
                "findings": [],
            }
        )
    ).build()
    nodes = set(graph.get_graph().nodes)
    assert {
        "inspect_goal_and_evidence",
        "inspect_action_scope_route",
        "inspect_constraints_policy",
    } <= nodes
    assert "inspect_action_scope_and_route" not in nodes
    assert "inspect_constraints_and_policy_summary" not in nodes


def test_six_role_runtime_calls_all_applicable_exact_inspectors_read_only() -> None:
    calls: list[str] = []

    class FakeAtomicReview:
        def semantic_invoker(
            self,
            _state: Mapping[str, object],
            *,
            on_result: Callable[[StructuredLLMResult], None],
        ) -> Callable[[str, Mapping[str, object]], Mapping[str, object]]:
            def invoke(prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
                calls.append(prompt_id)
                output = {
                    "schema_version": 1,
                    "dimension": prompt_id,
                    "findings": [],
                }
                on_result(_llm_result(output))
                return output

            return invoke

    runtime = object.__new__(RuntimeActiveReviewSubgraph)
    runtime._atomic_review = FakeAtomicReview()  # type: ignore[attr-defined]
    ids = iter(["review-1"])
    runtime._id_factory = ids.__next__  # type: ignore[attr-defined]
    route = {"output_plan": {"output_mode": "ACTION", "output_routes": []}}
    state = {
        "run_id": "run-1",
        "request_intent": {"constraints": []},
        "planning_result": {"schema_version": 2, "actions": []},
        "tool_route_plan": route,
        "policy_summary": {},
    }

    result, _llm = runtime._run_atomic_inspection(  # type: ignore[attr-defined]
        cast(object, state),
        evidence_drafts=[],
        confirmation_response=None,
    )

    assert result["status"] == "PASS"
    assert calls == [
        "review.inspect_goal_and_evidence",
        "review.inspect_action_scope_and_route",
        "review.inspect_constraints_and_policy_summary",
    ]
    assert route == {"output_plan": {"output_mode": "ACTION", "output_routes": []}}


def _llm_result(output: object) -> StructuredLLMResult:
    return StructuredLLMResult(
        structured_output=output,
        provider="fake",
        model="fake",
        requested_mode=RequestedRuntimeMode.AUTO,
        actual_runtime=ActualRuntime.API_LLM,
        input_tokens=1,
        output_tokens=1,
        total_tokens=2,
        latency_ms=1,
        estimated_cost_usd=None,
        fallback_reason=None,
        structured_output_attempts=1,
        provider_request_id="request-1",
        safe_error_code=None,
    )
