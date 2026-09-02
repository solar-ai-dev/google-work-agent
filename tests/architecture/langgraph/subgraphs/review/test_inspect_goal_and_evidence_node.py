from __future__ import annotations

import inspect
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import pytest
from tests.support.canonical_prompt_runtime import (
    copy_prompt_runtime_artifacts,
    deactivate_prompt_slot,
)

from google_work_agent.adapters.langgraph.subgraphs.review.graph import (
    ReviewRuntimeDependencies,
    ReviewSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.review.nodes import (
    inspect_goal_and_evidence_node as goal_node,
)
from google_work_agent.adapters.langgraph.subgraphs.review.projections import (
    inspect_goal_and_evidence_projection as goal_projection,
)
from google_work_agent.adapters.langgraph.subgraphs.review.routing import (
    route_after_inspect_goal_and_evidence as goal_route,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    InactivePromptArtifactError,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import (
    StructuredInferenceResultV1,
)

DIMENSION = "review.inspect_goal_and_evidence"


def test_goal_node__projection_and_answer__router_are_exact() -> None:
    state = {
        "request_intent": {},
        "planning_result": {"schema_version": 2, "answer": "draft"},
        "tool_route_plan": {"secret": "must not project"},
        "evidence": [],
    }
    assert set(goal_projection.project_inspect_goal_and_evidence_input(state)) == {
        "request_intent",
        "planning_result",
        "evidence",
    }
    patch = goal_node.inspect_goal_and_evidence_node(
        state,
        invoke=lambda _prompt_id, _input: {
            "schema_version": 1,
            "dimension": DIMENSION,
            "findings": [],
        },
    )
    assert set(patch) == {"goal_evidence_result"}
    assert goal_route.route_after_inspect_goal_and_evidence({**state, **patch}) == (
        "aggregate_findings"
    )


def test_non_active__goal_prompt_fails__before_structured_inference(tmp_path: Path) -> None:
    class FailingRuntime:
        calls = 0

        def infer(
            self,
            requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
            prompt_ref: PromptReference,
            input_projection: Mapping[str, object],
            output_schema_ref: OutputSchemaDefinition,
        ) -> StructuredInferenceResultV1:
            self.calls += 1
            raise AssertionError("inactive Prompt must not reach StructuredInferencePort")

    runtime = FailingRuntime()
    manifest_path, _contract_path = copy_prompt_runtime_artifacts(tmp_path)
    deactivate_prompt_slot(manifest_path, "review.inspect_goal_and_evidence")
    graph = ReviewSubgraph(
        llm_runtime=runtime,
        prompt_manifest_path=manifest_path,
    )
    invoke = graph.semantic_invoker({"run_id": "run-1"})

    with pytest.raises(InactivePromptArtifactError, match="not activation-gate complete"):
        invoke(
            "review.inspect_goal_and_evidence",
            {"request_intent": {}, "planning_result": {}, "evidence": []},
        )
    assert runtime.calls == 0


def test_production_inspection_has__no_broad_plan__review_semantic_caller() -> None:
    source = inspect.getsource(ReviewSubgraph)
    assert "inspect_goal_and_evidence_node" in source
    assert "inspect_action_scope_and_route_node" in source
    assert "inspect_constraints_and_policy_summary_node" in source
    assert "invoke_inspect_llm" not in source
    assert "RuntimeActiveReviewSubgraph" not in source


def test_review_graph__uses_exact_atomic__runtime_node_ids() -> None:
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


def test_six_role_runtime__calls_all_applicable__exact_inspectors_read_only() -> None:
    calls: list[str] = []

    def invoke(prompt_id: str, _prompt_input: object) -> dict[str, object]:
        calls.append(prompt_id)
        return {"schema_version": 1, "dimension": prompt_id, "findings": []}

    route = {"output_plan": {"output_mode": "ACTION", "output_routes": []}}
    result = (
        ReviewSubgraph(
            dependencies=ReviewRuntimeDependencies(invoke=invoke)  # type: ignore[arg-type]
        )
        .build()
        .invoke(
            {
                "run_id": "run-1",
                "request_intent": {"constraints": []},
                "planning_result": {"schema_version": 2, "actions": []},
                "tool_route_plan": route,
                "policy_summary": {},
                "evidence": [],
                "review_phase": "INITIAL",
                "review_artifact_id": "review-1",
                "review_revision": 1,
                "review_based_on": [],
            }
        )
    )

    assert result["review_result"]["status"] == "PASS"
    assert calls == [
        "review.inspect_goal_and_evidence",
        "review.inspect_action_scope_and_route",
    ]
    assert route == {"output_plan": {"output_mode": "ACTION", "output_routes": []}}
