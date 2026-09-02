"""Compare two completed experiments without making a Product promotion decision."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from evaluation.runner import write_result


class ExperimentComparisonError(ValueError):
    """Raised when two result sets are incomplete or not controlled-comparable."""


def compare_experiment_results(
    baseline_directory: Path, candidate_directory: Path
) -> dict[str, object]:
    """Return case/aggregate deltas after enforcing every fixed Prompt variable."""

    baseline_plan = _load_object(baseline_directory / "experiment-plan.json")
    candidate_plan = _load_object(candidate_directory / "experiment-plan.json")
    baseline_summary = _load_object(baseline_directory / "summary.json")
    candidate_summary = _load_object(candidate_directory / "summary.json")
    _require_prompt_comparison_controls(baseline_plan, candidate_plan)

    baseline_trials = _load_trials(baseline_directory, baseline_plan)
    candidate_trials = _load_trials(candidate_directory, candidate_plan)
    if set(baseline_trials) != set(candidate_trials):
        raise ExperimentComparisonError("trial identities differ between result sets")

    case_ids = _plan_case_ids(baseline_plan)
    improved: list[str] = []
    regressed: list[str] = []
    unchanged: list[str] = []
    hard_gate_regressions: list[str] = []
    case_deltas: dict[str, dict[str, object]] = {}
    for case_id in case_ids:
        baseline_case = [
            row for (trial_case, _), row in baseline_trials.items() if trial_case == case_id
        ]
        candidate_case = [
            row for (trial_case, _), row in candidate_trials.items() if trial_case == case_id
        ]
        baseline_all = all(_metric(row, "passed") for row in baseline_case)
        candidate_all = all(_metric(row, "passed") for row in candidate_case)
        if candidate_all and not baseline_all:
            improved.append(case_id)
            classification = "IMPROVED"
        elif baseline_all and not candidate_all:
            regressed.append(case_id)
            classification = "REGRESSED"
        else:
            unchanged.append(case_id)
            classification = "UNCHANGED"
        trial_hard_regressions = [
            trial_number
            for (trial_case, trial_number), baseline_row in baseline_trials.items()
            if trial_case == case_id
            and _metric(baseline_row, "hard_gate_passed")
            and not _metric(candidate_trials[(trial_case, trial_number)], "hard_gate_passed")
        ]
        if trial_hard_regressions:
            hard_gate_regressions.append(case_id)
        case_deltas[case_id] = {
            "classification": classification,
            "baseline_passed_trials": sum(_metric(row, "passed") for row in baseline_case),
            "candidate_passed_trials": sum(_metric(row, "passed") for row in candidate_case),
            "hard_gate_regressed_trials": trial_hard_regressions,
        }

    result = {
        "schema_version": 1,
        "comparison_group": baseline_plan["comparison_group"],
        "baseline_experiment_id": baseline_plan["experiment_id"],
        "candidate_experiment_id": candidate_plan["experiment_id"],
        "baseline_prompt_candidate_id": _prompt_candidate_id(baseline_plan),
        "candidate_prompt_candidate_id": _prompt_candidate_id(candidate_plan),
        "case_level_delta": case_deltas,
        "improved_cases": improved,
        "regressed_cases": regressed,
        "unchanged_cases": unchanged,
        "hard_gate_regressions": hard_gate_regressions,
        "aggregate_pass_delta": _summary_float(candidate_summary, "pass_rate")
        - _summary_float(baseline_summary, "pass_rate"),
        "consistency_delta": _summary_float(candidate_summary, "pass_power_k")
        - _summary_float(baseline_summary, "pass_power_k"),
        "promotion_status": (
            "NOT_PROMOTABLE" if hard_gate_regressions else "REQUIRES_SEPARATE_PRODUCT_DECISION"
        ),
    }
    return result


def _require_prompt_comparison_controls(
    baseline: Mapping[str, object], candidate: Mapping[str, object]
) -> None:
    if baseline.get("experiment_kind") != "PROMPT" or candidate.get("experiment_kind") != "PROMPT":
        raise ExperimentComparisonError("both experiments must be PROMPT experiments")
    for field in ("comparison_group", "product_sha", "repetitions"):
        if baseline.get(field) != candidate.get(field):
            raise ExperimentComparisonError(f"Prompt comparison fixed field differs: {field}")
    for field in ("dataset", "grader"):
        if _nested_hash(baseline, field) != _nested_hash(candidate, field):
            raise ExperimentComparisonError(f"Prompt comparison artifact differs: {field}")
    if _candidate_config_field(baseline, "fixed_configuration_hash") != _candidate_config_field(
        candidate, "fixed_configuration_hash"
    ):
        raise ExperimentComparisonError("model/profile/runtime configuration differs")
    if _plan_case_ids(baseline) != _plan_case_ids(candidate):
        raise ExperimentComparisonError("Prompt comparison case IDs differ")
    if _prompt_candidate_id(baseline) == _prompt_candidate_id(candidate):
        raise ExperimentComparisonError("Prompt comparison requires two distinct candidates")


def _load_trials(
    directory: Path, plan: Mapping[str, object]
) -> dict[tuple[str, int], dict[str, object]]:
    expected_repetitions = _required_int(plan, "repetitions")
    expected = {
        (case_id, trial_number)
        for case_id in _plan_case_ids(plan)
        for trial_number in range(1, expected_repetitions + 1)
    }
    result: dict[tuple[str, int], dict[str, object]] = {}
    for path in sorted((directory / "cases").glob("*/trial-*.json")):
        row = _load_object(path)
        provenance = _mapping(row.get("experiment_provenance"), "experiment_provenance")
        case_id = _required_string(provenance, "case_id")
        trial_number = _required_int(provenance, "trial_number")
        key = (case_id, trial_number)
        if key in result:
            raise ExperimentComparisonError(f"duplicate trial identity: {key}")
        result[key] = row
    if set(result) != expected:
        raise ExperimentComparisonError(
            f"trial set mismatch: missing={sorted(expected - set(result))}, "
            f"extra={sorted(set(result) - expected)}"
        )
    return result


def _plan_case_ids(plan: Mapping[str, object]) -> list[str]:
    dataset = _mapping(plan.get("dataset"), "dataset")
    case_ids = dataset.get("case_ids")
    if not isinstance(case_ids, list) or not all(isinstance(item, str) for item in case_ids):
        raise ExperimentComparisonError("dataset.case_ids must be a string array")
    return cast(list[str], case_ids)


def _prompt_candidate_id(plan: Mapping[str, object]) -> str:
    prompt = _mapping(plan.get("prompt_candidate"), "prompt_candidate")
    return _required_string(prompt, "candidate_id")


def _candidate_config_field(plan: Mapping[str, object], field: str) -> object:
    config = _mapping(plan.get("candidate_config"), "candidate_config")
    return config.get(field)


def _nested_hash(plan: Mapping[str, object], field: str) -> object:
    artifact = _mapping(plan.get(field), field)
    return artifact.get("sha256")


def _metric(trial: Mapping[str, object], field: str) -> bool:
    metrics = _mapping(trial.get("metrics"), "metrics")
    value = metrics.get(field)
    if not isinstance(value, bool):
        raise ExperimentComparisonError(f"metrics.{field} must be boolean")
    return value


def _summary_float(summary: Mapping[str, object], field: str) -> float:
    value = summary.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ExperimentComparisonError(f"summary.{field} must be numeric")
    return float(value)


def _load_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExperimentComparisonError(f"cannot load result artifact: {path}") from error
    if not isinstance(value, dict):
        raise ExperimentComparisonError(f"result artifact must be an object: {path}")
    return cast(dict[str, object], value)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ExperimentComparisonError(f"{field} must be an object")
    return cast(Mapping[str, object], value)


def _required_string(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise ExperimentComparisonError(f"{field} must be a non-empty string")
    return value


def _required_int(payload: Mapping[str, object], field: str) -> int:
    value = payload.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ExperimentComparisonError(f"{field} must be an integer")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare controlled Evaluation result sets")
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(argv)
    try:
        result = compare_experiment_results(arguments.baseline, arguments.candidate)
    except ExperimentComparisonError as error:
        print(json.dumps({"status": "INVALID", "reason": str(error)}, sort_keys=True))
        return 2
    if arguments.output is None:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        write_result(arguments.output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ExperimentComparisonError", "compare_experiment_results"]
