"""Real Product-profile witness over one current Evaluation fixture."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from evaluation.configs.load_experiment_config import load_experiment_config
from evaluation.contracts.current_fixture_snapshot import CurrentFixtureSnapshotV1
from evaluation.contracts.experiment_config import EvaluationBudgetV1, ExperimentTargetV1
from evaluation.datasets.load_canonical_cases import load_canonical_cases
from evaluation.fixtures.load_current_fixture import load_current_fixture
from evaluation.fixtures.product_resource_projection import project_product_resources
from evaluation.reporting.write_results import RESULT_FILENAMES
from evaluation.runner.run_experiment import run_experiment
from evaluation.targets.main_profile_product_target import execute_main_profile_product_target
from evaluation.targets.target_registry import resolve_target
from pydantic import JsonValue
from tests.integration.langgraph.test_runtime import (
    FakeGoogleGateway,
    _llm_result,
    _make_runtime_with_llm,
    _QueuedLLMRuntime,
    _runtime_active_manifest_path,
    _seed_runtime_database,
)
from tests.support.checkpoint import sqlite_checkpoint
from tests.support.fixtures.loader import ProductFixtureManifest, ProductFixtureSnapshot

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    account_provider_dispatch,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm import StructuredLLMResult
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


class _CurrentFixtureLLM(_QueuedLLMRuntime):
    def __init__(self) -> None:
        super().__init__(
            [
                {
                    "schema_version": 2,
                    "goal": "선택한 Boreal 메일에서 최종 서명 기한과 법무 담당을 확인한다.",
                    "completion_conditions": ["근거가 있는 기한과 담당자를 답한다."],
                    "constraints": [],
                    "ambiguity": {
                        "requires_confirmation": False,
                        "reason_codes": [],
                        "missing_fields": [],
                    },
                    "requested_effect_hints": ["READ"],
                    "requested_resource_hints": ["GMAIL_THREAD"],
                    "analysis_requirement": "NONE",
                }
            ]
        )
        self.selected_evidence_id: str | None = None

    def _invoke(self, **kwargs: object) -> StructuredLLMResult:
        prompt_ref = kwargs.get("prompt_ref")
        prompt_id = getattr(prompt_ref, "prompt_id", None)
        prompt_input = cast(Mapping[str, object], kwargs.get("prompt_input", {}))
        if prompt_id == "retrieval.plan_query":
            account_provider_dispatch()
            self.calls.append(dict(kwargs))
            routes = [
                route
                for route in cast(list[dict[str, object]], prompt_input["input_routes"])
                if route.get("resource_refs")
            ]
            return _llm_result(
                {
                    "schema_version": 2,
                    "route_queries": [
                        {
                            "route_id": route["route_id"],
                            "operation": "SEARCH",
                            "reason_codes": ["REQUIRED"],
                            "search_spec": {
                                "mode": "INITIAL",
                                "constraints": [
                                    {
                                        "kind": "RESOURCE_REF",
                                        "resource_refs": route["resource_refs"],
                                    },
                                    {
                                        "kind": "KEYWORD",
                                        "terms": ["Boreal"],
                                        "match_mode": "ANY",
                                    },
                                ],
                            },
                            "detail_candidate_ref": None,
                        }
                        for route in routes
                    ],
                    "required_information": ["최종 서명 기한", "법무 담당"],
                    "retrieval_order": [route["route_id"] for route in routes],
                }
            )
        if prompt_id == "retrieval.select_evidence":
            account_provider_dispatch()
            self.calls.append(dict(kwargs))
            ranked = cast(list[Mapping[str, object]], prompt_input["ranked_segments"])
            selected = next(
                (item for item in ranked if "최종 서명 기한" in str(item["excerpt"])), None
            )
            assert selected is not None, [str(item.get("excerpt")) for item in ranked]
            segment_id = str(selected["segment_id"])
            self.selected_evidence_id = f"evidence-{segment_id}"
            return _llm_result(
                {
                    "schema_version": 2,
                    "selected_segment_ids": [segment_id],
                    "evidence_drafts": [
                        {
                            "segment_id": segment_id,
                            "role": "SUPPORTS",
                            "relevance_reason": "최종 서명 기한과 담당자를 직접 명시한다.",
                        }
                    ],
                    "excluded_segment_ids": [],
                }
            )
        if prompt_id == "retrieval.assess_sufficiency":
            account_provider_dispatch()
            self.calls.append(dict(kwargs))
            return _llm_result({"schema_version": 2, "status": "SUFFICIENT", "issues": []})
        if prompt_id == "planning.compose_answer":
            account_provider_dispatch()
            self.calls.append(dict(kwargs))
            assert self.selected_evidence_id is not None
            return _llm_result(
                {
                    "schema_version": 2,
                    "answer": "최종 서명 기한은 8월 16일 18시이며 법무 담당은 소라입니다.",
                    "evidence_refs": [self.selected_evidence_id],
                }
            )
        return super()._invoke(**kwargs)


def _request(product_input: Mapping[str, object]) -> WorkflowStartRequest:
    handles = tuple(cast(list[str], product_input["selected_resource_handles"]))
    return WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode=str(product_input["entry_mode"]),
        requested_mode="AUTO",
        request_text=str(product_input["user_prompt"]),
        selected_resource_ids=handles,
        selected_resources=tuple(
            SelectedResourceRef(
                source="GMAIL",
                resource_type="THREAD",
                resource_id=resource_id,
            )
            for resource_id in handles
        ),
        run_budget=cast(dict[str, Any], build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )


def _runtime_dependencies(
    root: Path,
    product_input: dict[str, JsonValue],
    fixture: CurrentFixtureSnapshotV1,
) -> Mapping[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    product_snapshot = ProductFixtureSnapshot(
        manifest=ProductFixtureManifest(
            snapshot_id=fixture.fixture_snapshot_id,
            resource_paths=(),
            fault_paths=(),
        ),
        resources=project_product_resources(fixture),
        faults=(),
    )
    gateway = FakeGoogleGateway(product_snapshot)
    database_path = _seed_runtime_database(root)
    llm_runtime = _CurrentFixtureLLM()
    runtime = _make_runtime_with_llm(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=gateway,
        checkpoint_port=sqlite_checkpoint(root / "checkpoints-evaluation.db"),
        prompt_manifest_path=_runtime_active_manifest_path(root),
    )
    request = _request(cast(Mapping[str, object], product_input))

    def output_adapter(output: Mapping[str, object]) -> Mapping[str, object]:
        answer = cast(Mapping[str, object], output["answer_draft"])
        retrieval = cast(Mapping[str, object], output["retrieval_result"])
        evidence_refs = cast(list[str], retrieval["source_resource_refs"])
        tool_names = {
            "get_gmail_thread": "gmail_get_thread",
            "get_gmail_message": "gmail_get_message",
            "search_gmail_threads": "gmail_search_threads",
        }
        observed_calls: list[dict[str, object]] = []
        for call in gateway.call_log:
            tool = tool_names.get(call.operation)
            if tool is None:
                continue
            resource_ids = [
                value
                for key, value in call.arguments.items()
                if key in {"resource_id", "thread_id", "message_id"} and isinstance(value, str)
            ]
            observed_calls.append(
                {
                    "tool": tool,
                    "effect": "READ",
                    "phase": "RETRIEVAL_READ",
                    "arguments": {"resource_ids": resource_ids},
                }
            )
        connection = connect_sqlite(database_path)
        try:
            run_status = connection.execute(
                "SELECT status FROM runs WHERE id = 'run-1'"
            ).fetchone()[0]
        finally:
            connection.close()
        observed_node_ids = [
            str(getattr(call.get("prompt_ref"), "prompt_id", "unknown"))
            for call in llm_runtime.calls
        ]
        return {
            "answer_artifact": {
                "text": str(answer["answer"]),
                "evidence_ids": cast(list[str], answer["evidence_refs"]),
                "evidence_resource_refs": evidence_refs,
            },
            "interactions": [],
            "observed_tool_calls": observed_calls,
            "approval_events": [],
            "unknown_result_events": [],
            "durable_effects": [],
            "terminal_state": str(run_status),
            "node_results": [
                {
                    "schema_version": 1,
                    "target_id": "six_role_baseline",
                    "status": str(run_status),
                }
            ],
            "routing_trajectory": {
                "schema_version": 2,
                "case_id": "CASE-CORE-001",
                "topology_scope": "SIX_ROLE_BASELINE",
                "observed_node_ids": observed_node_ids,
                "observed_tool_ids": [row["tool"] for row in observed_calls],
                "skipped_node_ids": [],
                "budget_snapshot": {
                    "llm_call_count": len(llm_runtime.calls),
                    "google_api_call_count": len(gateway.call_log),
                },
                "diagnostic_only": True,
            },
            "usage": {
                "agent_run_count": 1,
                "llm_call_count": len(llm_runtime.calls),
                "provider_http_request_count": len(llm_runtime.calls),
                "google_api_call_count": len(gateway.call_log),
                "cost_usd": 0.0,
            },
        }

    return {
        "main_profile": {
            "bindings": runtime._graph_node_bindings,
            "control_bindings": runtime._main_graph_control_bindings,
            "route_next_node": runtime._route_next_node,
            "checkpointer": None,
            "input_adapter": lambda _: runtime._initial_state(request),
            "output_adapter": output_adapter,
        },
        "cleanup": runtime.close,
    }


def test_real_six_role_main_profile_runs_against_current_fixture(tmp_path: Path) -> None:
    fixture = load_current_fixture("FW-D-002")
    product_snapshot = ProductFixtureSnapshot(
        manifest=ProductFixtureManifest(
            snapshot_id=fixture.fixture_snapshot_id,
            resource_paths=(),
            fault_paths=(),
        ),
        resources=project_product_resources(fixture),
        faults=(),
    )
    gateway = FakeGoogleGateway(product_snapshot)
    database_path = _seed_runtime_database(tmp_path)
    runtime = _make_runtime_with_llm(
        database_path=database_path,
        llm_runtime=_CurrentFixtureLLM(),
        gateway=gateway,
        checkpoint_port=sqlite_checkpoint(tmp_path / "checkpoints-evaluation.db"),
        prompt_manifest_path=_runtime_active_manifest_path(tmp_path),
    )
    request = WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="RESOURCE_SELECTED",
        requested_mode="AUTO",
        request_text=(
            "선택한 Boreal 갱신 메일을 다시 확인해서 최종 서명 기한과 법무 담당을 "
            "보여줘. 다른 메일은 검색하지 마."
        ),
        selected_resource_ids=("GTH-B-001",),
        selected_resources=(
            SelectedResourceRef(
                source="GMAIL",
                resource_type="THREAD",
                resource_id="GTH-B-001",
            ),
        ),
        run_budget=cast(dict[str, Any], build_default_run_budget()),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
    )
    target = resolve_target(
        ExperimentTargetV1(
            schema_version=1,
            target_kind="MAIN_PROFILE",
            target_id="six_role_baseline",
        )
    )
    try:
        result = execute_main_profile_product_target(
            target,
            {
                "runtime_item_id": "item_780bd37bca0233b6edf9d8c3",
                "user_prompt": request.request_text,
                "entry_mode": request.entry_mode,
                "selected_resource_handles": ["GTH-B-001"],
                "fixture_snapshot_id": fixture.fixture_snapshot_id,
            },
            builder_arguments={
                "bindings": runtime._graph_node_bindings,
                "control_bindings": runtime._main_graph_control_bindings,
                "route_next_node": runtime._route_next_node,
                "checkpointer": None,
                "input_adapter": lambda _: runtime._initial_state(request),
            },
        )
    finally:
        runtime.close()

    rows = cast(list[dict[str, object]], result["node_results"])
    output = cast(dict[str, object], rows[0]["output"])
    answer = cast(Mapping[str, object], output["answer_draft"])
    assert answer["answer"] == "최종 서명 기한은 8월 16일 18시이며 법무 담당은 소라입니다."
    assert [call.operation for call in gateway.call_log].count("get_gmail_thread") == 1


def test_runner_executes_real_six_role_profile_and_writes_exact_results(
    tmp_path: Path,
) -> None:
    case = next(case for case in load_canonical_cases() if case.case_id == "CASE-CORE-001")
    cases_path = tmp_path / "canonical_cases_v7.jsonl"
    cases_path.write_text(case.canonical_json() + "\n", encoding="utf-8")
    source_projections = (
        Path("evaluation/projections/data/e2e_projection_v5.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    projection_line = next(
        line for line in source_projections if json.loads(line)["case_id"] == case.case_id
    )
    projections_path = tmp_path / "e2e_projection_v5.jsonl"
    projections_path.write_text(projection_line + "\n", encoding="utf-8")

    base = load_experiment_config(Path("evaluation/configs/EXP-165-CORRECTIVE-MAIN.json"))
    config = base.model_copy(
        update={
            "experiment_id": "EXP-165-REAL-MAIN-WITNESS",
            "target": ExperimentTargetV1(
                schema_version=1,
                target_kind="MAIN_PROFILE",
                target_id="six_role_baseline",
            ),
            "budgets": EvaluationBudgetV1(
                schema_version=1,
                max_evaluation_items=1,
                max_agent_runs=1,
                max_llm_calls=20,
                max_provider_http_requests=20,
                max_google_api_calls=20,
                max_cost_usd=1.0,
            ),
        }
    )
    factory_calls = 0

    def dependency_factory(
        product_input: dict[str, JsonValue],
        fixture: CurrentFixtureSnapshotV1,
    ) -> Mapping[str, object]:
        nonlocal factory_calls
        factory_calls += 1
        return _runtime_dependencies(tmp_path / "runtime", product_input, fixture)

    target = run_experiment(
        config,
        target_dependencies={"factory": dependency_factory},
        cases_path=cases_path,
        projections_path=projections_path,
        results_root=tmp_path / "results",
    )

    assert factory_calls == 1
    assert tuple(sorted(path.name for path in target.iterdir())) == tuple(sorted(RESULT_FILENAMES))
    manifest = json.loads((target / "experiment_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((target / "summary_metrics.json").read_text(encoding="utf-8"))
    graders = [
        json.loads(line)
        for line in (target / "grader_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert manifest["run_status"] == "COMPLETE"
    assert manifest["target_id"] == "six_role_baseline"
    assert manifest["completed_item_count"] == 1
    assert summary["pass_count"] == summary["denominator"] == 1
    assert [row["verdict"] for row in graders[:5]] == ["PASS"] * 5
    assert graders[5]["verdict"] == "NOT_APPLICABLE"
    assert (target / "node_results.jsonl").read_text(encoding="utf-8").strip()
    assert (target / "trajectory_results.jsonl").read_text(encoding="utf-8").strip()
    assert "PENDING_HUMAN_REVIEW" in (target / "human_review.md").read_text(encoding="utf-8")
    assert "Decision: DEFERRED" in (target / "product_decision_record.md").read_text(
        encoding="utf-8"
    )
