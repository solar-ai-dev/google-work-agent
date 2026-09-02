"""Batch public-boundary Evaluation orchestration over the canonical one-case runner."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from getpass import getpass
from pathlib import Path
from typing import cast

from evaluation.client import ProductApiClient
from evaluation.experiment_plan import (
    ExperimentPlanError,
    ValidatedExperimentPlan,
    load_experiment_plan,
    validate_only_report,
)
from evaluation.runner import run_case, write_result

CaseExecutor = Callable[..., dict[str, object]]

_METRIC_OBSERVABILITY = {
    "schema_valid_first_pass": "NOT_OBSERVABLE_CURRENTLY",
    "schema_repair_count": "NOT_OBSERVABLE_CURRENTLY",
    "semantic_revision_count": "NOT_OBSERVABLE_CURRENTLY",
    "tool_selection_accuracy": "PARTIALLY_OBSERVABLE",
    "unnecessary_tool_rate": "PARTIALLY_OBSERVABLE",
    "missed_tool_rate": "PARTIALLY_OBSERVABLE",
    "argument_grounding": "NOT_OBSERVABLE_CURRENTLY",
    "scope_expansion_rate": "PARTIALLY_OBSERVABLE",
    "invented_identifier_rate": "NOT_OBSERVABLE_CURRENTLY",
    "false_confirmation_rate": "PARTIALLY_OBSERVABLE",
    "missed_confirmation_rate": "PARTIALLY_OBSERVABLE",
    "evidence_grounding": "PARTIALLY_OBSERVABLE",
    "retrieval_redundancy": "NOT_OBSERVABLE_CURRENTLY",
    "review_false_positive_rate": "NOT_OBSERVABLE_CURRENTLY",
    "review_false_negative_rate": "NOT_OBSERVABLE_CURRENTLY",
    "prompt_injection_resistance": "PARTIALLY_OBSERVABLE",
    "episode_success": "OBSERVABLE",
    "hard_gate_pass": "OBSERVABLE",
    "latency": "NOT_OBSERVABLE_CURRENTLY",
    "token_usage": "NOT_OBSERVABLE_CURRENTLY",
    "provider_calls": "NOT_OBSERVABLE_CURRENTLY",
}


def run_experiment(
    plan: ValidatedExperimentPlan,
    client: ProductApiClient,
    *,
    execute_case: CaseExecutor = run_case,
) -> dict[str, object]:
    """Run exact Case × repetition trials while preserving every raw result."""

    if not plan.runnable:
        raise ExperimentPlanError(
            f"experiment has unresolved bindings: {list(plan.unresolved_bindings)}"
        )
    output_root = plan.result_directory()
    if output_root.exists() and any(output_root.iterdir()):
        raise ExperimentPlanError("experiment result directory must be absent or empty")
    output_root.mkdir(parents=True, exist_ok=True)
    write_result(output_root / "experiment-plan.json", plan.provenance())

    requested_mode = _requested_mode(plan.candidate_config_payload)
    trials: list[dict[str, object]] = []
    stop = False
    for case in plan.cases:
        case_id = _required_string(case, "case_id")
        for trial_number in range(1, plan.repetitions + 1):
            try:
                result = execute_case(
                    client,
                    case=case,
                    dataset_path=plan.dataset.path,
                    product_sha=plan.product_sha,
                    experiment_name=plan.experiment_id,
                    candidate_id=plan.candidate_config_id,
                    requested_mode=requested_mode,
                )
                result["experiment_provenance"] = _trial_provenance(
                    plan, case_id=case_id, trial_number=trial_number
                )
            except Exception as error:
                result = _failed_trial(
                    plan,
                    case_id=case_id,
                    trial_number=trial_number,
                    error_type=type(error).__name__,
                )
                stop = plan.trial_failure_policy == "STOP"
            trial_path = output_root / "cases" / case_id / f"trial-{trial_number:03d}.json"
            write_result(trial_path, result)
            trials.append(result)
            if stop:
                break
        if stop:
            break

    summary = _build_summary(plan, trials)
    write_result(output_root / "summary.json", summary)
    return summary


def _trial_provenance(
    plan: ValidatedExperimentPlan, *, case_id: str, trial_number: int
) -> dict[str, object]:
    return {
        "experiment_id": plan.experiment_id,
        "comparison_group": plan.comparison_group,
        "product_sha": plan.product_sha,
        "case_id": case_id,
        "trial_number": trial_number,
        "dataset_path": plan.dataset.repository_path,
        "dataset_hash": plan.dataset.sha256,
        "grader_path": plan.grader.repository_path,
        "grader_hash": plan.grader.sha256,
        "candidate_config_id": plan.candidate_config_id,
        "candidate_config_hash": plan.candidate_config.sha256,
        "fixed_configuration_hash": plan.fixed_configuration_hash,
        "prompt_candidate_id": plan.prompt_candidate.candidate_id,
        "prompt_candidate_bundle_hash": plan.prompt_candidate.bundle_hash,
        "materialized_prompt_manifest_hash": (
            plan.prompt_candidate.materialized_prompt_manifest_hash
        ),
        "graph_profile": plan.candidate_config_payload.get("graph_version"),
        "runtime_mode": _requested_mode(plan.candidate_config_payload),
    }


def _failed_trial(
    plan: ValidatedExperimentPlan,
    *,
    case_id: str,
    trial_number: int,
    error_type: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "experiment_name": plan.experiment_id,
        "case_id": case_id,
        "candidate_id": plan.candidate_config_id,
        "product_sha": plan.product_sha,
        "metrics": {"passed": False, "hard_gate_passed": False},
        "error": {"reason_code": "TRIAL_EXECUTION_FAILED", "error_type": error_type},
        "experiment_provenance": _trial_provenance(
            plan, case_id=case_id, trial_number=trial_number
        ),
    }


def _build_summary(
    plan: ValidatedExperimentPlan, trials: list[dict[str, object]]
) -> dict[str, object]:
    by_case: dict[str, list[dict[str, object]]] = {case_id: [] for case_id in plan.case_ids}
    for trial in trials:
        by_case[_required_string(trial, "case_id")].append(trial)
    passed_trials = sum(_metric(trial, "passed") for trial in trials)
    hard_passed_trials = sum(_metric(trial, "hard_gate_passed") for trial in trials)
    any_pass_cases = sum(
        1 for case_trials in by_case.values() if any(_metric(row, "passed") for row in case_trials)
    )
    all_pass_cases = sum(
        1
        for case_trials in by_case.values()
        if len(case_trials) == plan.repetitions
        and all(_metric(row, "passed") for row in case_trials)
    )
    case_count = len(plan.case_ids)
    total_trials = len(trials)
    return {
        "schema_version": 1,
        "experiment_id": plan.experiment_id,
        "comparison_group": plan.comparison_group,
        "product_sha": plan.product_sha,
        "prompt_candidate_id": plan.prompt_candidate.candidate_id,
        "prompt_candidate_bundle_hash": plan.prompt_candidate.bundle_hash,
        "materialized_prompt_manifest_hash": (
            plan.prompt_candidate.materialized_prompt_manifest_hash
        ),
        "dataset_hash": plan.dataset.sha256,
        "grader_hash": plan.grader.sha256,
        "fixed_configuration_hash": plan.fixed_configuration_hash,
        "expected_trials": case_count * plan.repetitions,
        "total_trials": total_trials,
        "passed_trials": passed_trials,
        "hard_gate_passed_trials": hard_passed_trials,
        "pass_rate": _ratio(passed_trials, total_trials),
        "pass_at_k": _ratio(any_pass_cases, case_count),
        "pass_power_k": _ratio(all_pass_cases, case_count),
        "case_results": {
            case_id: {
                "completed_trials": len(case_trials),
                "passed_trials": sum(_metric(row, "passed") for row in case_trials),
                "hard_gate_passed_trials": sum(
                    _metric(row, "hard_gate_passed") for row in case_trials
                ),
            }
            for case_id, case_trials in sorted(by_case.items())
        },
        "metric_observability": dict(_METRIC_OBSERVABILITY),
    }


def _requested_mode(candidate_config: Mapping[str, object]) -> str:
    runtime = candidate_config.get("runtime")
    if not isinstance(runtime, Mapping):
        raise ExperimentPlanError("candidate config runtime must be an object")
    requested_mode = runtime.get("runtime_mode")
    if requested_mode not in {"AUTO", "LOCAL_GPU", "API_LLM"}:
        raise ExperimentPlanError("candidate config runtime_mode is invalid")
    return cast(str, requested_mode)


def _required_string(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise ExperimentPlanError(f"{field} must be a non-empty string")
    return value


def _metric(trial: Mapping[str, object], field: str) -> int:
    metrics = trial.get("metrics")
    return int(isinstance(metrics, Mapping) and metrics.get(field) is True)


def _ratio(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate or run one Evaluation experiment plan")
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--validate-only", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        plan = load_experiment_plan(arguments.plan, repository_root=arguments.repository_root)
        if arguments.validate_only:
            print(json.dumps(validate_only_report(plan), indent=2, sort_keys=True))
            return 0
        client = ProductApiClient(arguments.base_url)
        client.bootstrap(getpass("Product bootstrap secret: "))
        summary = run_experiment(plan, client)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0 if summary["passed_trials"] == summary["total_trials"] else 2
    except ExperimentPlanError as error:
        print(json.dumps({"status": "INVALID", "reason": str(error)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["run_experiment"]
