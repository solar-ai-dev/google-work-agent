from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

from evaluation.client import ProductApiClient
from evaluation.experiment_plan import ValidatedExperimentPlan, load_experiment_plan
from evaluation.run_experiment import run_experiment

ROOT = Path(__file__).parents[2]
BASELINE_PLAN = ROOT / "evaluation/configs/experiments/prompt-baseline-smoke.template.json"


class _ProductApiStub:
    def create_conversation(self, *, command_id: str, title: str) -> dict[str, object]:
        assert command_id and title
        return {"conversation_id": "conversation-1"}

    def start_run(self, **payload: object) -> dict[str, object]:
        assert payload["conversation_id"] == "conversation-1"
        return {"run_id": "run-1"}

    def wait_for_observable_result(self, run_id: str) -> dict[str, object]:
        assert run_id == "run-1"
        return {
            "run": {"status": "COMPLETED"},
            "messages": [{"role": "ASSISTANT", "content": "Grounded answer"}],
            "actions": [],
            "approvals": [],
            "verification_summary": {},
            "context_preview": {"resource_refs": ["resource:RES-1"]},
            "pending_interrupt": None,
        }


def _case(case_id: str) -> dict[str, object]:
    return {
        "case_id": case_id,
        "canonical_user_prompt": "Find the resource",
        "entry_mode": "AGENT_SEARCH",
        "selected_resource_handles": [],
        "requested_outcome": "ANSWER",
        "required_evidence_ids": [],
        "required_resource_ids": ["RES-1"],
        "forbidden_actions": [],
        "allowed_actions": [],
        "approval_expectation": {"required": False},
        "verification_expectation": {"required": False},
        "expected_interactions": [],
        "expected_tool_trajectory": [],
        "end_state_gold": {
            "terminal_expectation": "COMPLETED",
            "expected_mutations": [],
            "forbidden_mutations": [{"scope": "ALL", "rule": "UNCHANGED"}],
        },
    }


def _runnable_plan(tmp_path: Path) -> ValidatedExperimentPlan:
    loaded = load_experiment_plan(BASELINE_PLAN, repository_root=ROOT)
    cases = (_case("CASE-1"), _case("CASE-2"))
    return replace(
        loaded,
        experiment_id="batch-test",
        case_ids=("CASE-1", "CASE-2"),
        cases=cases,
        repetitions=2,
        results_root=tmp_path / "evaluation/results",
        unresolved_bindings=(),
        model_binding_status="READY",
    )


def test_batch_runner_executes__exact_n_times_k_and_preserves__provenance(
    tmp_path: Path,
) -> None:
    plan = _runnable_plan(tmp_path)
    summary = run_experiment(plan, cast(ProductApiClient, _ProductApiStub()))
    trial_paths = sorted(plan.result_directory().glob("cases/*/trial-*.json"))

    assert len(trial_paths) == 4
    assert summary["expected_trials"] == 4
    assert summary["total_trials"] == 4
    assert summary["passed_trials"] == 4
    assert summary["pass_at_k"] == 1.0
    assert summary["pass_power_k"] == 1.0
    first = trial_paths[0].read_text(encoding="utf-8")
    assert plan.prompt_candidate.candidate_id in first
    assert plan.prompt_candidate.bundle_hash in first
    assert plan.prompt_candidate.materialized_prompt_manifest_hash in first
    assert not list(plan.result_directory().rglob("*.tmp"))


def test_continue_policy__preserves_failure_and_runs__remaining_trials(tmp_path: Path) -> None:
    plan = _runnable_plan(tmp_path)
    calls = 0

    def execute_case(*_args: object, **kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        case = kwargs["case"]
        assert isinstance(case, dict)
        if calls == 1:
            raise RuntimeError("simulated public boundary failure")
        return {
            "schema_version": 1,
            "case_id": case["case_id"],
            "metrics": {"passed": True, "hard_gate_passed": True},
        }

    summary = run_experiment(
        plan,
        cast(ProductApiClient, _ProductApiStub()),
        execute_case=execute_case,
    )

    assert calls == 4
    assert summary["total_trials"] == 4
    assert summary["passed_trials"] == 3
    failed = (plan.result_directory() / "cases/CASE-1/trial-001.json").read_text(encoding="utf-8")
    assert "TRIAL_EXECUTION_FAILED" in failed
    assert "simulated public boundary failure" not in failed
