from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from evaluation.experiment_plan import (
    ExperimentPlanError,
    load_experiment_plan,
    validate_only_report,
)

ROOT = Path(__file__).parents[2]
BASELINE_PLAN = ROOT / "evaluation/configs/experiments/prompt-baseline-smoke.template.json"
CANDIDATE_PLAN = ROOT / "evaluation/configs/experiments/prompt-mcp-research-smoke.template.json"


def test_prompt_plan_templates_lock__same_controls_and_only_prompt__candidate() -> None:
    baseline = load_experiment_plan(BASELINE_PLAN, repository_root=ROOT)
    candidate = load_experiment_plan(CANDIDATE_PLAN, repository_root=ROOT)

    assert baseline.product_sha == candidate.product_sha
    assert baseline.dataset.sha256 == candidate.dataset.sha256
    assert baseline.case_ids == candidate.case_ids
    assert baseline.grader.sha256 == candidate.grader.sha256
    assert baseline.fixed_configuration_hash == candidate.fixed_configuration_hash
    assert baseline.repetitions == candidate.repetitions == 3
    assert baseline.prompt_candidate.candidate_id == "current-product-baseline"
    assert candidate.prompt_candidate.candidate_id == "mcp-tool-use-research-2026-v1"
    assert candidate.prompt_candidate.product_binding_status == (
        "PENDING_DEV_LAUNCH_INTEGRATION"
    )


def test_validate_only_reports__unresolved_model_prompt_and_split__without_execution() -> None:
    candidate = load_experiment_plan(CANDIDATE_PLAN, repository_root=ROOT)
    report = validate_only_report(candidate)

    assert report["experiment_plan_validation"] == "PASS"
    assert report["runtime_binding_status"] == "PENDING"
    assert report["prompt_candidate_product_binding"] == (
        "PENDING_DEV_LAUNCH_INTEGRATION"
    )
    assert report["model_binding_status"] == "PENDING"
    assert report["dev_split_status"] == "NEEDS_DATASET_DECISION"
    assert report["holdout_split_status"] == "NEEDS_DATASET_DECISION"
    assert report["expected_trials"] == 9


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda plan: plan.update(experiment_kind="UNKNOWN"), "unknown experiment kind"),
        (lambda plan: plan.update(repetitions=0), "repetitions must be at least 1"),
        (
            lambda plan: plan["dataset"].update(sha256="0" * 64),
            "dataset hash mismatch",
        ),
        (
            lambda plan: plan["dataset"].update(case_ids=["CASE-CORE-001"] * 2),
            "case_ids contains duplicates",
        ),
        (
            lambda plan: plan["dataset"].update(case_ids=["MISSING-CASE"]),
            "dataset is missing case IDs",
        ),
        (
            lambda plan: plan["prompt_candidate"].update(bundle_hash="0" * 64),
            "Prompt candidate is invalid|Prompt candidate identity mismatch",
        ),
    ],
)
def test_plan_rejects__closed_contract_and_identity__violations(
    tmp_path: Path, mutation: object, message: str
) -> None:
    plan = deepcopy(json.loads(CANDIDATE_PLAN.read_text(encoding="utf-8")))
    cast_mutation = mutation
    assert callable(cast_mutation)
    cast_mutation(plan)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ExperimentPlanError, match=message):
        load_experiment_plan(path, repository_root=ROOT)


def test_plan_rejects__extra_field__rather_than_growing_implicit_schema(
    tmp_path: Path,
) -> None:
    plan = json.loads(BASELINE_PLAN.read_text(encoding="utf-8"))
    plan["automatic_prompt_winner"] = True
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ExperimentPlanError, match="fields mismatch"):
        load_experiment_plan(path, repository_root=ROOT)
