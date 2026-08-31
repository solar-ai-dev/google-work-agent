from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, cast

import pytest
from evaluation.contracts.experiment_config import ExperimentTargetV1
from evaluation.targets.main_profile_product_target import execute_main_profile_product_target
from evaluation.targets.node_product_target import execute_node_product_target
from evaluation.targets.subgraph_product_target import execute_subgraph_product_target
from evaluation.targets.target_registry import (
    MAIN_PROFILE_TARGETS,
    NODE_TARGETS,
    SUBGRAPH_TARGETS,
    TargetResolutionError,
    resolve_target,
)
from tests.support.canonical_prompt_runtime import (
    activate_prompt_slot,
    copy_prompt_runtime_artifacts,
)

from google_work_agent.adapters.langgraph.main.graph import (
    GraphNodeBindings,
    MainControlNodeBindings,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.application.prompt_runtime.prompt_registry import load_prompt_reference
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


def _target(kind: str, target_id: str) -> ExperimentTargetV1:
    return cast(
        ExperimentTargetV1,
        ExperimentTargetV1.model_validate(
            {"schema_version": 1, "target_kind": kind, "target_id": target_id}, strict=True
        ),
    )


def test_registry_exactly_matches_21_prompt_nodes_six_subgraphs_and_three_profiles() -> None:
    manifest = json.loads(
        Path("src/google_work_agent/application/prompt_runtime/prompt_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(NODE_TARGETS) == {slot["runtime_node_id"] for slot in manifest["slots"]}
    assert set(SUBGRAPH_TARGETS) == {
        "request_understanding",
        "tool_routing",
        "retrieval",
        "work_analysis",
        "planning",
        "review",
    }
    assert set(MAIN_PROFILE_TARGETS) == {"single_baseline", "three_stage", "six_role_baseline"}
    for target_id in NODE_TARGETS:
        assert callable(resolve_target(_target("NODE", target_id)).load())
    for target_id in SUBGRAPH_TARGETS:
        assert isinstance(resolve_target(_target("SUBGRAPH", target_id)).load(), type)
    for target_id in MAIN_PROFILE_TARGETS:
        assert callable(resolve_target(_target("MAIN_PROFILE", target_id)).load())


def test_unknown_target_fails_closed() -> None:
    with pytest.raises(TargetResolutionError, match="unknown"):
        resolve_target(_target("NODE", "unknown.node"))


@pytest.mark.parametrize("profile_id", sorted(MAIN_PROFILE_TARGETS))
def test_real_main_profile_builders_compile_and_invoke_product_graph(profile_id: str) -> None:
    def unused(_: dict[str, object]) -> dict[str, object]:
        return {}

    def initialize(_: dict[str, object]) -> dict[str, object]:
        return {"__target__": "end"}

    node_bindings = GraphNodeBindings(
        request_understanding=unused,
        tool_route=unused,
        context_retriever=unused,
        work_analysis=unused,
        planning=unused,
        review=unused,
        single_workflow=unused,
        waiting_approval=unused,
        stage_one=unused,
        stage_two=unused,
        stage_three=unused,
    )
    control_bindings = MainControlNodeBindings(
        initialize=initialize,
        retrieval_entry=unused,
        planning_entry=unused,
        review_entry=unused,
        domain_validation=unused,
        preflight=unused,
        domain_reconcile=unused,
        action_execution=unused,
        verification=unused,
        recovery=unused,
        cancel_resolution=unused,
        response_synthesis=unused,
        terminal_commit=unused,
        finalize=unused,
    )
    target = resolve_target(_target("MAIN_PROFILE", profile_id))
    result = execute_main_profile_product_target(
        target,
        {},
        builder_arguments={
            "bindings": node_bindings,
            "control_bindings": control_bindings,
            "route_next_node": lambda state: state["__target__"],
            "checkpointer": None,
        },
    )
    rows = cast(list[dict[str, object]], result["node_results"])
    assert rows[0]["target_id"] == profile_id


def test_real_node_boundary_invokes_exact_product_function_and_surfaces_contract_error() -> None:
    target = resolve_target(_target("NODE", "retrieval.plan_query"))
    with pytest.raises(ValueError, match="missing typed input projection"):
        execute_node_product_target(target, {"runtime_item_id": "opaque"})


class _RequestRuntime:
    def infer(
        self,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        del requested_mode, input_projection, output_schema_ref
        output: dict[str, object] = (
            {
                "goal": "관련 메일 확인",
                "completion_conditions": ["근거를 답한다"],
                "constraints": [],
                "requested_effect_hints": ["READ"],
                "requested_resource_hints": ["GMAIL_THREAD"],
                "analysis_requirement": "REQUIRED",
            }
            if prompt_ref.prompt_id == "request_understanding.identify_goal"
            else {"requires_confirmation": False, "reason_codes": [], "missing_fields": []}
        )
        return StructuredInferenceResultV1(
            schema_version=1,
            structured_output=output,
            provider="fake",
            model="fake",
            actual_runtime="API_LLM",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            fallback_reason=None,
        )


def test_real_identify_goal_node_invokes_and_returns_typed_product_patch(tmp_path: Path) -> None:
    manifest_path, _ = copy_prompt_runtime_artifacts(tmp_path)
    activate_prompt_slot(manifest_path, "request_understanding.identify_goal")
    request = WorkflowStartRequest(
        run_id="node-run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="관련 메일을 확인해 줘",
        selected_resource_ids=(),
        run_budget=cast(dict[str, Any], build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )
    target = resolve_target(_target("NODE", "request.identify_goal"))
    result = execute_node_product_target(
        target,
        {
            "schema_version": 1,
            "run_id": request.run_id,
            "__request__": request,
            "run_input": {
                "entry_mode": request.entry_mode,
                "user_request": request.request_text,
                "selected_resource_refs": [],
                "requested_mode": request.requested_mode,
            },
            "retry_budget": build_default_run_budget(),
            "prompt_context": {},
            "trace_context": {},
        },
        dependencies={
            "llm_runtime": _RequestRuntime(),
            "prompt_ref": load_prompt_reference(
                "request_understanding.identify_goal", manifest_path
            ),
        },
    )
    rows = cast(list[dict[str, object]], result["node_results"])
    patch = cast(dict[str, object], rows[0]["output"])
    goal_candidate = cast(dict[str, object], patch["goal_candidate"])
    retry_budget = cast(dict[str, object], patch["retry_budget"])
    assert goal_candidate["goal"] == "관련 메일 확인"
    assert retry_budget["llm_calls_used"] == 0


def test_real_request_understanding_subgraph_compiles_and_invokes(tmp_path: Path) -> None:
    manifest_path, _ = copy_prompt_runtime_artifacts(tmp_path)
    activate_prompt_slot(manifest_path, "request_understanding.identify_goal")
    activate_prompt_slot(manifest_path, "request_understanding.detect_ambiguity")
    request = WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="관련 메일을 확인해 줘",
        selected_resource_ids=(),
        run_budget=cast(dict[str, Any], build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )
    target = resolve_target(_target("SUBGRAPH", "request_understanding"))

    def merge(state: object, update: object, decision: Mapping[str, object]) -> dict[str, object]:
        assert isinstance(state, Mapping) and isinstance(update, Mapping)
        return {**state, **update, "__target__": decision["target"]}

    result = execute_subgraph_product_target(
        target,
        {
            "schema_version": 1,
            "run_id": "run-1",
            "__request__": request,
            "run_input": {
                "entry_mode": "AGENT_SEARCH",
                "user_request": "관련 메일을 확인해 줘",
                "selected_resource_refs": [],
                "requested_mode": "AUTO",
            },
            "retry_budget": build_default_run_budget(),
            "prompt_context": {},
            "trace_context": {},
        },
        constructor_arguments={
            "llm_runtime": _RequestRuntime(),
            "prompt_manifest_path": manifest_path,
            "id_factory": lambda: "evaluation-invocation",
            "graph_profile": GraphProfile.SIX_ROLE_BASELINE,
            "transition_run": lambda _run_id, _event: None,
            "merge_decision": merge,
            "confirm_inline": lambda _state: (None, None),
        },
    )
    rows = cast(list[dict[str, object]], result["node_results"])
    assert rows[0]["target_id"] == "request_understanding"
