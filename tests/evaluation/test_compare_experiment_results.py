from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from evaluation.client import ProductApiClient
from evaluation.compare_experiment_results import (
    ExperimentComparisonError,
    compare_experiment_results,
)
from evaluation.experiment_plan import ValidatedExperimentPlan, load_experiment_plan
from evaluation.run_experiment import run_experiment

ROOT = Path(__file__).parents[2]
BASELINE_PLAN = ROOT / "evaluation/configs/experiments/prompt-baseline-smoke.template.json"


def _case(case_id: str) -> dict[str, object]:
    return {"case_id": case_id}


def _result(case_id: str, *, passed: bool, hard_gate_passed: bool) -> dict[str, object]:
    return {
        "schema_version": 1,
        "case_id": case_id,
        "metrics": {"passed": passed, "hard_gate_passed": hard_gate_passed},
    }


def _plan(
    tmp_path: Path, experiment_id: str, prompt_id: str
) -> ValidatedExperimentPlan:
    loaded = load_experiment_plan(BASELINE_PLAN, repository_root=ROOT)
    prompt = replace(loaded.prompt_candidate, candidate_id=prompt_id)
    return replace(
        loaded,
        experiment_id=experiment_id,
        case_ids=("CASE-1", "CASE-2"),
        cases=(_case("CASE-1"), _case("CASE-2")),
        repetitions=2,
        results_root=tmp_path / "evaluation/results",
        prompt_candidate=prompt,
        unresolved_bindings=(),
        model_binding_status="READY",
    )


def test_comparison_classifies_delta_and_blocks__new_hard_gate_failure(
    tmp_path: Path,
) -> None:
    baseline = _plan(tmp_path, "baseline", "prompt-a")
    candidate = _plan(tmp_path, "candidate", "prompt-b")

    def baseline_executor(*_args: object, **kwargs: object) -> dict[str, object]:
        case = kwargs["case"]
        assert isinstance(case, dict)
        return _result(cast(str, case["case_id"]), passed=True, hard_gate_passed=True)

    candidate_calls = 0

    def candidate_executor(*_args: object, **kwargs: object) -> dict[str, object]:
        nonlocal candidate_calls
        candidate_calls += 1
        case = kwargs["case"]
        assert isinstance(case, dict)
        failed = candidate_calls == 1
        return _result(
            cast(str, case["case_id"]),
            passed=not failed,
            hard_gate_passed=not failed,
        )

    client = cast(ProductApiClient, object())
    run_experiment(baseline, client, execute_case=baseline_executor)
    run_experiment(candidate, client, execute_case=candidate_executor)
    comparison = compare_experiment_results(
        baseline.result_directory(), candidate.result_directory()
    )

    assert comparison["regressed_cases"] == ["CASE-1"]
    assert comparison["hard_gate_regressions"] == ["CASE-1"]
    assert comparison["promotion_status"] == "NOT_PROMOTABLE"
    assert comparison["aggregate_pass_delta"] == -0.25


def test_comparison_rejects__different_product_or_fixed_model_profile(
    tmp_path: Path,
) -> None:
    baseline = _plan(tmp_path, "baseline", "prompt-a")
    candidate = replace(
        _plan(tmp_path, "candidate", "prompt-b"), product_sha="b" * 40
    )

    def executor(*_args: object, **kwargs: object) -> dict[str, object]:
        case = kwargs["case"]
        assert isinstance(case, dict)
        return _result(cast(str, case["case_id"]), passed=True, hard_gate_passed=True)

    client = cast(ProductApiClient, object())
    run_experiment(baseline, client, execute_case=executor)
    run_experiment(candidate, client, execute_case=executor)

    with pytest.raises(ExperimentComparisonError, match="product_sha"):
        compare_experiment_results(
            baseline.result_directory(), candidate.result_directory()
        )


@pytest.mark.parametrize(
    ("field", "expected_message"),
    [
        ("fixed_configuration_hash", "model/profile/runtime configuration differs"),
        ("dataset_hash", "Prompt comparison artifact differs: dataset"),
    ],
)
def test_comparison_rejects__different_fixed_control(
    tmp_path: Path, field: str, expected_message: str
) -> None:
    baseline = _plan(tmp_path, "baseline", "prompt-a")
    candidate = _plan(tmp_path, "candidate", "prompt-b")
    if field == "fixed_configuration_hash":
        candidate = replace(candidate, fixed_configuration_hash="c" * 64)
    else:
        candidate = replace(
            candidate,
            dataset=replace(candidate.dataset, sha256="d" * 64),
        )

    def executor(*_args: object, **kwargs: object) -> dict[str, object]:
        case = kwargs["case"]
        assert isinstance(case, dict)
        return _result(cast(str, case["case_id"]), passed=True, hard_gate_passed=True)

    client = cast(ProductApiClient, object())
    run_experiment(baseline, client, execute_case=executor)
    run_experiment(candidate, client, execute_case=executor)

    with pytest.raises(ExperimentComparisonError, match=expected_message):
        compare_experiment_results(
            baseline.result_directory(), candidate.result_directory()
        )


def test_comparison_rejects__missing_trial(tmp_path: Path) -> None:
    baseline = _plan(tmp_path, "baseline", "prompt-a")
    candidate = _plan(tmp_path, "candidate", "prompt-b")

    def executor(*_args: object, **kwargs: object) -> dict[str, object]:
        case = kwargs["case"]
        assert isinstance(case, dict)
        return _result(cast(str, case["case_id"]), passed=True, hard_gate_passed=True)

    client = cast(ProductApiClient, object())
    run_experiment(baseline, client, execute_case=executor)
    run_experiment(candidate, client, execute_case=executor)
    (candidate.result_directory() / "cases/CASE-1/trial-001.json").unlink()

    with pytest.raises(ExperimentComparisonError, match="trial set mismatch"):
        compare_experiment_results(
            baseline.result_directory(), candidate.result_directory()
        )
