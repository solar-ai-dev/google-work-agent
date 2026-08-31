"""Evaluation-only orchestration across current datasets, graders, and results."""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal, cast

from pydantic import JsonValue, field_validator, model_validator

from evaluation.contracts.e2e_projection import E2EProjectionV5
from evaluation.contracts.evaluation_contract import EvaluationContract, load_strict_json
from evaluation.contracts.routing_trajectory_projection import RoutingTrajectoryProjectionV2
from evaluation.datasets.load_canonical_cases import (
    DEFAULT_CANONICAL_CASES_PATH,
    CanonicalCaseV7,
    load_canonical_cases,
)
from evaluation.graders.grade_item import GraderResultV1, grade_item, load_scoring_contract
from evaluation.projections.build_current_projections import (
    DEFAULT_PROJECTION_DATA_DIR,
    E2E_PROJECTION_FILENAME,
)
from evaluation.reporting.write_results import EvaluationResultSetV1, write_results

DEFAULT_RESULTS_ROOT = Path(__file__).parents[1] / "results"
CURRENT_GRADER_IDS = (
    "safety_contract_deterministic",
    "user_interaction_deterministic",
    "tool_trajectory_deterministic",
    "end_state_deterministic",
    "semantic_completion_supporting",
)
_PRODUCT_INPUT_FORBIDDEN_FIELDS = {
    "gold",
    "end_state_gold",
    "decision_script",
    "grader",
    "grader_feedback",
    "score",
    "expected_route",
    "expected_output",
    "six_reference_route",
    "holdout_metadata",
}


class ExperimentRunError(ValueError):
    """Raised when an Evaluation run violates its isolated runner contract."""


class EvaluationBudgetV1(EvaluationContract):
    schema_version: Literal[1]
    max_evaluation_items: int
    max_agent_runs: int
    max_llm_calls: int
    max_provider_http_requests: int
    max_google_api_calls: int
    max_cost_usd: float

    @field_validator(
        "max_evaluation_items",
        "max_agent_runs",
        "max_llm_calls",
        "max_provider_http_requests",
        "max_google_api_calls",
    )
    @classmethod
    def _require_positive_limit(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("budget count limits must be positive")
        return value

    @field_validator("max_cost_usd")
    @classmethod
    def _require_positive_cost(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("max_cost_usd must be positive")
        return value


class ExperimentConfigV1(EvaluationContract):
    schema_version: Literal[1]
    experiment_id: str
    experiment_kind: Literal["A", "B", "C", "D", "E"]
    hypothesis: str
    independent_variable: str
    fixed_variables: dict[str, JsonValue]
    dataset_version: str
    projection_version: str
    fixture_snapshot_hash: str
    candidate_config_hash: str
    graph_version: str
    prompt_id: str
    prompt_bundle_version: str
    agent_schema_version: str
    tool_schema_version: str
    policy_version: str
    retrieval_config_version: str
    runtime_mode: str
    provider: str
    model_id: str
    model_version: str
    runtime_parameters: dict[str, JsonValue]
    hardware_profile: str
    target_node_id: str | None
    upstream_mode: Literal["ORACLE", "LIVE"] | None
    trial_count: int
    grader_version: Literal["0.4"]
    stop_conditions: dict[str, JsonValue]
    adoption_criteria: dict[str, JsonValue]
    runner_version: str
    seed: int
    partition: Literal["CORE", "HOLDOUT", "STRESS"]
    candidate_config: dict[str, JsonValue]
    config_diff: dict[str, JsonValue]
    product_commit_sha: str
    budgets: EvaluationBudgetV1

    @field_validator("experiment_id")
    @classmethod
    def _validate_experiment_id(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
            raise ValueError("invalid experiment_id")
        return value

    @field_validator(
        "hypothesis",
        "independent_variable",
        "dataset_version",
        "projection_version",
        "graph_version",
        "prompt_id",
        "prompt_bundle_version",
        "agent_schema_version",
        "tool_schema_version",
        "policy_version",
        "retrieval_config_version",
        "runtime_mode",
        "provider",
        "model_id",
        "model_version",
        "hardware_profile",
        "runner_version",
    )
    @classmethod
    def _require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("runner identity fields must be non-empty")
        return value

    @field_validator("fixture_snapshot_hash", "candidate_config_hash")
    @classmethod
    def _validate_artifact_hash(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("artifact hashes must be full lowercase SHA-256 values")
        return value

    @field_validator("product_commit_sha")
    @classmethod
    def _validate_commit_sha(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise ValueError("product_commit_sha must be a full lowercase Git SHA")
        return value

    @field_validator("trial_count")
    @classmethod
    def _require_positive_trial_count(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("trial_count must be positive")
        return value

    @model_validator(mode="after")
    def _verify_candidate_hash(self) -> ExperimentConfigV1:
        if self.candidate_config_hash != _stable_json_hash(self.candidate_config):
            raise ValueError("candidate_config_hash does not match candidate_config")
        return self


ProductEvaluationBoundary = Callable[[dict[str, JsonValue]], Mapping[str, object]]


def run_experiment(
    config: ExperimentConfigV1,
    *,
    execute_product: ProductEvaluationBoundary,
    cases_path: Path = DEFAULT_CANONICAL_CASES_PATH,
    projections_path: Path = DEFAULT_PROJECTION_DATA_DIR / E2E_PROJECTION_FILENAME,
    results_root: Path = DEFAULT_RESULTS_ROOT,
) -> Path:
    """Run one isolated, reproducible Evaluation experiment and write all artifacts."""

    cases = load_canonical_cases(cases_path)
    projections = _load_e2e_projections(projections_path)
    _validate_projection_closure(cases, projections)
    selected = _select_cases(cases, config)
    candidate_hash = _stable_json_hash(config.candidate_config)
    dataset_hash = _file_hash(cases_path)
    projection_hash = _file_hash(projections_path)
    scoring = load_scoring_contract()

    evaluation_items: list[dict[str, JsonValue]] = []
    node_results: list[dict[str, JsonValue]] = []
    trajectory_results: list[dict[str, JsonValue]] = []
    grader_results: list[dict[str, JsonValue]] = []
    case_failures: list[dict[str, JsonValue]] = []
    completed_count = 0
    usage = _empty_usage()
    bts_pass_count = 0

    stop_requested = False
    attempted_count = 0
    for case in selected:
        projection = projections[case.case_id]
        for trial_index in range(config.trial_count):
            attempted_count += 1
            evaluation_item_id = f"{config.experiment_id}:{case.case_id}:trial-{trial_index}"
            evaluation_items.append(
                {
                    "schema_version": 1,
                    "experiment_id": config.experiment_id,
                    "evaluation_item_id": evaluation_item_id,
                    "case_id": case.case_id,
                    "user_prompt_id": case.user_prompt_id,
                    "fixture_snapshot_id": case.fixture_snapshot_id,
                    "candidate_config_hash": candidate_hash,
                    "partition": case.split,
                    "trial_index": trial_index,
                    "prompt_id": config.prompt_id,
                    "model_id": config.model_id,
                    "graph_version": config.graph_version,
                    "projection_hash": projection.stable_hash(),
                    "product_commit_sha": config.product_commit_sha,
                }
            )
            try:
                product_input = _gold_free_product_input(projection)
                observed = execute_product(product_input)
                if not isinstance(observed, Mapping):
                    raise ExperimentRunError("Product evaluation boundary must return an object")
                item_usage = _read_usage(observed)
                usage = _add_usage(usage, item_usage)
                _enforce_budget(
                    config.budgets,
                    usage,
                    completed_items=attempted_count,
                )
                item_graders = [
                    grade_item(grader_id, projection=projection, observed=observed)
                    for grader_id in CURRENT_GRADER_IDS
                ]
                grader_results.extend(
                    _grader_row(
                        result,
                        config=config,
                        evaluation_item_id=evaluation_item_id,
                        case_id=case.case_id,
                        candidate_hash=candidate_hash,
                        trial_index=trial_index,
                    )
                    for result in item_graders
                )
                _append_node_results(
                    node_results,
                    observed=observed,
                    config=config,
                    evaluation_item_id=evaluation_item_id,
                    case_id=case.case_id,
                    candidate_hash=candidate_hash,
                    trial_index=trial_index,
                )
                _append_trajectory_result(
                    trajectory_results,
                    observed=observed,
                    config=config,
                    evaluation_item_id=evaluation_item_id,
                    case_id=case.case_id,
                    candidate_hash=candidate_hash,
                    trial_index=trial_index,
                )
                if _business_task_success(projection, item_graders):
                    bts_pass_count += 1
                else:
                    case_failures.append(
                        _failure_row(
                            config=config,
                            evaluation_item_id=evaluation_item_id,
                            case_id=case.case_id,
                            candidate_hash=candidate_hash,
                            trial_index=trial_index,
                            failure_kind="CANDIDATE_RESULT",
                            reason_codes=[
                                reason
                                for result in item_graders
                                if result.verdict == "FAIL"
                                for reason in result.reason_codes
                            ],
                        )
                    )
                completed_count += 1
            except Exception as error:
                case_failures.append(
                    _failure_row(
                        config=config,
                        evaluation_item_id=evaluation_item_id,
                        case_id=case.case_id,
                        candidate_hash=candidate_hash,
                        trial_index=trial_index,
                        failure_kind="RUNNER_OR_BOUNDARY_FAILURE",
                        reason_codes=[type(error).__name__],
                    )
                )
                stop_requested = True
                break
        if stop_requested:
            break

    expected_item_count = len(selected) * config.trial_count
    run_status = "COMPLETE" if completed_count == expected_item_count else "PARTIAL"
    denominator = completed_count
    result_set = EvaluationResultSetV1(
        schema_version=1,
        experiment_manifest={
            "schema_version": 1,
            "experiment_id": config.experiment_id,
            "experiment_kind": config.experiment_kind,
            "hypothesis": config.hypothesis,
            "independent_variable": config.independent_variable,
            "fixed_variables": config.fixed_variables,
            "run_status": run_status,
            "runner_version": config.runner_version,
            "seed": config.seed,
            "partition": config.partition,
            "candidate_config_hash": candidate_hash,
            "product_commit_sha": config.product_commit_sha,
            "dataset_hash": dataset_hash,
            "dataset_version": config.dataset_version,
            "projection_hash": projection_hash,
            "projection_version": config.projection_version,
            "fixture_snapshot_hash": config.fixture_snapshot_hash,
            "graph_version": config.graph_version,
            "prompt_id": config.prompt_id,
            "prompt_bundle_version": config.prompt_bundle_version,
            "agent_schema_version": config.agent_schema_version,
            "tool_schema_version": config.tool_schema_version,
            "policy_version": config.policy_version,
            "retrieval_config_version": config.retrieval_config_version,
            "runtime_mode": config.runtime_mode,
            "provider": config.provider,
            "model_id": config.model_id,
            "model_version": config.model_version,
            "runtime_parameters": config.runtime_parameters,
            "hardware_profile": config.hardware_profile,
            "target_node_id": config.target_node_id,
            "upstream_mode": config.upstream_mode,
            "trial_count": config.trial_count,
            "scoring_contract_version": cast(JsonValue, scoring["schema_version"]),
            "grader_registry_version": cast(JsonValue, scoring["grader_registry_version"]),
            "grader_version": config.grader_version,
            "stop_conditions": config.stop_conditions,
            "adoption_criteria": config.adoption_criteria,
            "evaluation_item_count": expected_item_count,
            "completed_item_count": completed_count,
        },
        candidate_config=config.candidate_config,
        config_diff={
            "independent_variable": config.independent_variable,
            "changes": config.config_diff,
        },
        evaluation_items=evaluation_items,
        node_results=node_results,
        trajectory_results=trajectory_results,
        grader_results=grader_results,
        case_failures=case_failures,
        summary_metrics={
            "schema_version": 1,
            "denominator_group": config.partition,
            "pass_count": bts_pass_count,
            "denominator": denominator,
            "percentage": (bts_pass_count / denominator * 100.0) if denominator else 0.0,
            "business_task_success": bts_pass_count,
            "safety_and_outcome_kept_separate": True,
            "run_status": run_status,
        },
        budget_report={"schema_version": 1, "limits": config.budgets.model_dump(), **usage},
        human_review=(
            "# Human review\n\n"
            "Status: PENDING_HUMAN_REVIEW\n\n"
            "No human-review PASS is claimed by the automated runner."
        ),
        product_decision_record=(
            "# Product decision record\n\n"
            "Decision: DEFERRED\n\n"
            "A release decision requires the applicable holdout, safety, and human-review evidence."
        ),
    )
    return write_results(
        experiment_id=config.experiment_id,
        result_set=result_set,
        results_root=results_root,
    )


def _load_e2e_projections(path: Path) -> dict[str, E2EProjectionV5]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ExperimentRunError("cannot read current E2E projections") from error
    rows: dict[str, E2EProjectionV5] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise ExperimentRunError(f"blank E2E projection row at line {line_number}")
        projection = E2EProjectionV5.model_validate(load_strict_json(line), strict=True)
        if projection.case_id in rows:
            raise ExperimentRunError(f"duplicate E2E projection case_id: {projection.case_id}")
        rows[projection.case_id] = projection
    return rows


def _validate_projection_closure(
    cases: tuple[CanonicalCaseV7, ...],
    projections: Mapping[str, E2EProjectionV5],
) -> None:
    case_ids = {case.case_id for case in cases}
    if case_ids != set(projections):
        raise ExperimentRunError("canonical case and E2E projection identity sets differ")
    for case in cases:
        projection = projections[case.case_id]
        if projection.fixture_snapshot_id != case.fixture_snapshot_id:
            raise ExperimentRunError(f"fixture mismatch for {case.case_id}")


def _select_cases(
    cases: tuple[CanonicalCaseV7, ...],
    config: ExperimentConfigV1,
) -> list[CanonicalCaseV7]:
    partition = [case for case in cases if case.split == config.partition]
    if not partition:
        raise ExperimentRunError(f"partition has no evaluation cases: {config.partition}")
    max_cases = config.budgets.max_evaluation_items // config.trial_count
    if max_cases <= 0:
        raise ExperimentRunError("max_evaluation_items cannot cover one complete trial set")
    limit = min(len(partition), max_cases)
    if limit == len(partition):
        return partition
    sampled = random.Random(config.seed).sample(partition, limit)
    return sorted(sampled, key=lambda case: case.case_id)


def _gold_free_product_input(projection: E2EProjectionV5) -> dict[str, JsonValue]:
    value = projection.product_input
    if not isinstance(value, dict):
        raise ExperimentRunError("E2E product_input must be an object")
    copied: object = json.loads(json.dumps(value, ensure_ascii=False))
    if not isinstance(copied, dict):
        raise ExperimentRunError("E2E product_input copy must be an object")
    _reject_forbidden_product_fields(copied)
    return cast(dict[str, JsonValue], copied)


def _reject_forbidden_product_fields(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in _PRODUCT_INPUT_FORBIDDEN_FIELDS:
                raise ExperimentRunError(f"Evaluation-only field leaked to Product input: {key}")
            _reject_forbidden_product_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_forbidden_product_fields(nested)


def _read_usage(observed: Mapping[str, object]) -> dict[str, JsonValue]:
    raw = observed.get("usage", {})
    if not isinstance(raw, Mapping):
        raise ExperimentRunError("observed.usage must be an object")
    fields = (
        "agent_run_count",
        "llm_call_count",
        "provider_http_request_count",
        "google_api_call_count",
    )
    usage: dict[str, JsonValue] = {}
    for field in fields:
        value = raw.get(field, 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ExperimentRunError(f"usage.{field} must be a non-negative integer")
        usage[field] = value
    cost = raw.get("cost_usd", 0.0)
    if not isinstance(cost, (int, float)) or isinstance(cost, bool) or cost < 0:
        raise ExperimentRunError("usage.cost_usd must be a non-negative number")
    usage["cost_usd"] = float(cost)
    return usage


def _empty_usage() -> dict[str, JsonValue]:
    return {
        "agent_run_count": 0,
        "llm_call_count": 0,
        "provider_http_request_count": 0,
        "google_api_call_count": 0,
        "cost_usd": 0.0,
    }


def _add_usage(total: dict[str, JsonValue], item: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        field: cast(float | int, total[field]) + cast(float | int, item[field]) for field in total
    }


def _enforce_budget(
    limits: EvaluationBudgetV1,
    usage: Mapping[str, JsonValue],
    *,
    completed_items: int,
) -> None:
    checks = {
        "evaluation_item_count": (completed_items, limits.max_evaluation_items),
        "agent_run_count": (usage["agent_run_count"], limits.max_agent_runs),
        "llm_call_count": (usage["llm_call_count"], limits.max_llm_calls),
        "provider_http_request_count": (
            usage["provider_http_request_count"],
            limits.max_provider_http_requests,
        ),
        "google_api_call_count": (usage["google_api_call_count"], limits.max_google_api_calls),
        "cost_usd": (usage["cost_usd"], limits.max_cost_usd),
    }
    exceeded = [name for name, (actual, limit) in checks.items() if cast(float, actual) > limit]
    if exceeded:
        raise ExperimentRunError(f"evaluation budget exceeded: {exceeded}")


def _grader_row(
    result: GraderResultV1,
    *,
    config: ExperimentConfigV1,
    evaluation_item_id: str,
    case_id: str,
    candidate_hash: str,
    trial_index: int,
) -> dict[str, JsonValue]:
    return {
        "schema_version": 1,
        **_result_identity(
            config=config,
            evaluation_item_id=evaluation_item_id,
            case_id=case_id,
            candidate_hash=candidate_hash,
            trial_index=trial_index,
        ),
        **result.model_dump(mode="json"),
    }


def _failure_row(
    *,
    config: ExperimentConfigV1,
    evaluation_item_id: str,
    case_id: str,
    candidate_hash: str,
    trial_index: int,
    failure_kind: str,
    reason_codes: list[str],
) -> dict[str, JsonValue]:
    return {
        "schema_version": 1,
        **_result_identity(
            config=config,
            evaluation_item_id=evaluation_item_id,
            case_id=case_id,
            candidate_hash=candidate_hash,
            trial_index=trial_index,
        ),
        "failure_kind": failure_kind,
        "reason_codes": cast(JsonValue, reason_codes),
    }


def _business_task_success(
    projection: E2EProjectionV5,
    results: list[GraderResultV1],
) -> bool:
    by_id = {result.grader_id: result for result in results}
    hard_gate = all(
        by_id[grader_id].verdict == "PASS"
        for grader_id in ("safety_contract_deterministic", "user_interaction_deterministic")
    )
    end_state = by_id["end_state_deterministic"].verdict == "PASS"
    semantic_verdict = by_id["semantic_completion_supporting"].verdict
    business_gold = projection.business_gold
    if not isinstance(business_gold, dict):
        raise ExperimentRunError("business_gold must be an object")
    requested_outcome = business_gold.get("requested_outcome")
    if requested_outcome == "ANSWER":
        outcome = semantic_verdict == "PASS"
    else:
        outcome = end_state and semantic_verdict in {"PASS", "NOT_APPLICABLE"}
    return hard_gate and outcome


def _append_node_results(
    output: list[dict[str, JsonValue]],
    *,
    observed: Mapping[str, object],
    config: ExperimentConfigV1,
    evaluation_item_id: str,
    case_id: str,
    candidate_hash: str,
    trial_index: int,
) -> None:
    rows = observed.get("node_results", [])
    if not isinstance(rows, list):
        raise ExperimentRunError("observed.node_results must be an array")
    for row in rows:
        if not isinstance(row, dict) or not all(isinstance(key, str) for key in row):
            raise ExperimentRunError("node result rows must be objects")
        output.append(
            {
                **cast(dict[str, JsonValue], row),
                **_result_identity(
                    config=config,
                    evaluation_item_id=evaluation_item_id,
                    case_id=case_id,
                    candidate_hash=candidate_hash,
                    trial_index=trial_index,
                ),
            }
        )


def _append_trajectory_result(
    output: list[dict[str, JsonValue]],
    *,
    observed: Mapping[str, object],
    config: ExperimentConfigV1,
    evaluation_item_id: str,
    case_id: str,
    candidate_hash: str,
    trial_index: int,
) -> None:
    raw = observed.get("routing_trajectory")
    if raw is None:
        return
    trajectory = RoutingTrajectoryProjectionV2.model_validate(raw, strict=True)
    if trajectory.case_id != case_id:
        raise ExperimentRunError("routing trajectory case_id does not match evaluation item")
    output.append(
        {
            **trajectory.model_dump(mode="json"),
            **_result_identity(
                config=config,
                evaluation_item_id=evaluation_item_id,
                case_id=case_id,
                candidate_hash=candidate_hash,
                trial_index=trial_index,
            ),
        }
    )


def _result_identity(
    *,
    config: ExperimentConfigV1,
    evaluation_item_id: str,
    case_id: str,
    candidate_hash: str,
    trial_index: int,
) -> dict[str, JsonValue]:
    return {
        "experiment_id": config.experiment_id,
        "evaluation_item_id": evaluation_item_id,
        "case_id": case_id,
        "candidate_config_hash": candidate_hash,
        "trial_index": trial_index,
        "prompt_id": config.prompt_id,
        "model_id": config.model_id,
        "graph_version": config.graph_version,
    }


def _stable_json_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    return hashlib.sha256(payload).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "DEFAULT_RESULTS_ROOT",
    "EvaluationBudgetV1",
    "ExperimentConfigV1",
    "ExperimentRunError",
    "ProductEvaluationBoundary",
    "run_experiment",
]
