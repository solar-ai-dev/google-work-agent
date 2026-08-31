from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest
from evaluation.contracts.experiment_config import ExperimentTargetV1
from evaluation.projections.build_current_projections import build_current_projections
from evaluation.runner.run_experiment import (
    EvaluationBudgetV1,
    ExperimentConfigV1,
    ExperimentRunError,
    _call_with_timeout,
    run_experiment,
)
from pydantic import JsonValue
from tests.evaluation.conftest import make_case, make_episode


def _config(
    *,
    max_agent_runs: int = 2,
    max_evaluation_items: int = 1,
    trial_count: int = 1,
) -> ExperimentConfigV1:
    candidate_config: dict[str, JsonValue] = {
        "candidate_id": "candidate-a",
        "model_id": "synthetic",
    }
    candidate_hash = hashlib.sha256(
        json.dumps(
            candidate_config,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return ExperimentConfigV1(
        schema_version=1,
        experiment_id="EXP-RUNNER-001",
        experiment_kind="A",
        hypothesis="candidate preserves the fixed Product contract",
        independent_variable="model_id",
        fixed_variables={"policy_version": "policy-v1"},
        dataset_version="dataset-v7",
        projection_version="e2e-v5",
        fixture_snapshot_hash="b" * 64,
        candidate_config_hash=candidate_hash,
        graph_version="graph-v1",
        prompt_id="request-understanding-v1",
        prompt_bundle_version="prompt-bundle-v1",
        agent_schema_version="agent-schema-v1",
        tool_schema_version="tool-schema-v1",
        policy_version="policy-v1",
        retrieval_config_version="retrieval-v1",
        runtime_mode="RUNNER_MECHANICS_TEST",
        provider="synthetic",
        model_id="synthetic",
        model_version="v1",
        runtime_parameters={"temperature": 0},
        hardware_profile="test",
        target=ExperimentTargetV1(
            schema_version=1,
            target_kind="NODE",
            target_id="retrieval.plan_query",
        ),
        upstream_mode=None,
        trial_count=trial_count,
        grader_version="0.5",
        stop_conditions={"budget_exceeded": True},
        adoption_criteria={"safety_gate": "PASS"},
        runner_version="runner-v1",
        seed=17,
        partition="CORE",
        candidate_config=candidate_config,
        config_diff={"model_id": "synthetic"},
        product_commit_sha="a" * 40,
        budgets=EvaluationBudgetV1(
            schema_version=1,
            max_evaluation_items=max_evaluation_items,
            max_agent_runs=max_agent_runs,
            max_llm_calls=2,
            max_provider_http_requests=2,
            max_google_api_calls=2,
            max_cost_usd=1.0,
        ),
    )


def _inputs(tmp_path: Path) -> tuple[Path, Path]:
    case = make_case()
    cases_path = tmp_path / "canonical_cases_v7.jsonl"
    cases_path.write_text(case.canonical_json() + "\n", encoding="utf-8")
    projection_dir = tmp_path / "projections"
    build = build_current_projections(
        cases=[case],
        product_episodes=[make_episode()],
        output_dir=projection_dir,
    )
    return cases_path, build.e2e_path


def _fixture_root(tmp_path: Path) -> Path:
    root = tmp_path / "fixtures"
    target = root / "FW-CORE-001"
    target.mkdir(parents=True)
    world = {
        "schema_version": 1,
        "fixture_snapshot_id": "FW-CORE-001",
        "scenario_family_ids": ["SF-CORE-001"],
        "fixture_relation_family": "RF-CORE-001",
        "locale": "ko-KR",
        "timezone": "Asia/Seoul",
        "as_of": "2026-08-07T14:09:00+09:00",
        "permissions": {"gmail": "READ_ONLY"},
        "tool_availability": ["gmail_get_thread"],
    }
    files = {
        "fixture-world.json": world,
        "gmail.json": {"schema_version": 1, "threads": []},
        "tasks.json": {"schema_version": 1, "tasklists": [], "tasks": []},
        "calendar.json": {"schema_version": 1, "calendars": [], "events": []},
        "relations.json": {"schema_version": 1, "relations": []},
    }
    for name, payload in files.items():
        (target / name).write_text(json.dumps(payload), encoding="utf-8")
    return root


def test_runner_passes_only_gold_free_product_input_and_writes_complete_result(
    tmp_path: Path,
) -> None:
    case = make_case()
    cases_path, projections_path = _inputs(tmp_path)
    received: list[dict[str, object]] = []

    def execute_product(product_input: dict[str, JsonValue]) -> dict[str, object]:
        received.append(dict(product_input))
        return {
            "answer_artifact": {"text": "근거 답변", "evidence_ids": ["evidence-1"]},
            "interactions": [],
            "observed_tool_calls": [
                {
                    "tool": "gmail_get_thread",
                    "phase": "RETRIEVAL_READ",
                    "arguments": {"resource_ids": ["resource-1"]},
                }
            ],
            "approval_events": [],
            "unknown_result_events": [],
            "durable_effects": [],
            "terminal_state": "COMPLETED",
            "node_results": [],
            "usage": {
                "agent_run_count": 1,
                "llm_call_count": 1,
                "provider_http_request_count": 1,
                "google_api_call_count": 0,
                "cost_usd": 0.01,
            },
        }

    target = run_experiment(
        _config(),
        execute_product=execute_product,
        cases_path=cases_path,
        projections_path=projections_path,
        fixture_root=_fixture_root(tmp_path),
        results_root=tmp_path / "results",
    )

    assert len(received) == 1
    assert not {
        "gold",
        "end_state_gold",
        "decision_script",
        "grader",
        "expected_route",
    } & set(received[0])
    manifest = json.loads((target / "experiment_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((target / "summary_metrics.json").read_text(encoding="utf-8"))
    assert manifest["run_status"] == "COMPLETE"
    assert manifest["seed"] == 17
    assert manifest["product_commit_sha"] == "a" * 40
    assert manifest["candidate_config_hash"] == _config().candidate_config_hash
    item = json.loads((target / "evaluation_items.jsonl").read_text(encoding="utf-8"))
    assert item["user_prompt_id"] == case.user_prompt_id
    assert item["prompt_id"] == "request-understanding-v1"
    assert item["model_id"] == "synthetic"
    assert item["graph_version"] == "graph-v1"
    assert summary["pass_count"] == 1
    assert summary["denominator_group"] == "CORE"


def test_runner_marks_budget_failure_partial_instead_of_complete(tmp_path: Path) -> None:
    cases_path, projections_path = _inputs(tmp_path)

    def over_budget(_: dict[str, JsonValue]) -> dict[str, object]:
        return {
            "usage": {
                "agent_run_count": 2,
                "llm_call_count": 0,
                "provider_http_request_count": 0,
                "google_api_call_count": 0,
                "cost_usd": 0.0,
            }
        }

    target = run_experiment(
        _config(max_agent_runs=1),
        execute_product=over_budget,
        cases_path=cases_path,
        projections_path=projections_path,
        fixture_root=_fixture_root(tmp_path),
        results_root=tmp_path / "results",
    )

    manifest = json.loads((target / "experiment_manifest.json").read_text(encoding="utf-8"))
    failures = [
        json.loads(line)
        for line in (target / "case_failures.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert manifest["run_status"] == "PARTIAL"
    assert manifest["completed_item_count"] == 0
    assert failures[0]["failure_kind"] == "RUNNER_OR_BOUNDARY_FAILURE"


def test_runner_materializes_each_configured_trial_with_stable_identity(tmp_path: Path) -> None:
    cases_path, projections_path = _inputs(tmp_path)

    def execute_product(_: dict[str, JsonValue]) -> dict[str, object]:
        return {
            "answer_artifact": {"text": "근거 답변", "evidence_ids": ["evidence-1"]},
            "interactions": [],
            "observed_tool_calls": [
                {
                    "tool": "gmail_get_thread",
                    "phase": "RETRIEVAL_READ",
                    "arguments": {"resource_ids": ["resource-1"]},
                }
            ],
            "approval_events": [],
            "unknown_result_events": [],
            "durable_effects": [],
            "terminal_state": "COMPLETED",
            "node_results": [],
            "usage": {
                "agent_run_count": 1,
                "llm_call_count": 1,
                "provider_http_request_count": 1,
                "google_api_call_count": 0,
                "cost_usd": 0.01,
            },
        }

    target = run_experiment(
        _config(
            trial_count=2,
            max_evaluation_items=2,
            max_agent_runs=2,
        ),
        execute_product=execute_product,
        cases_path=cases_path,
        projections_path=projections_path,
        fixture_root=_fixture_root(tmp_path),
        results_root=tmp_path / "results",
    )

    items = [
        json.loads(line)
        for line in (target / "evaluation_items.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [item["trial_index"] for item in items] == [0, 1]
    assert len({item["evaluation_item_id"] for item in items}) == 2


def test_product_target_timeout_fails_closed_without_waiting_for_completion() -> None:
    started_at = time.monotonic()

    def slow_product() -> dict[str, object]:
        time.sleep(0.2)
        return {}

    with pytest.raises(ExperimentRunError, match="timed out"):
        _call_with_timeout(slow_product, timeout_seconds=0.01)

    assert time.monotonic() - started_at < 0.15
