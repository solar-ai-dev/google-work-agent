"""Closed validation contract for reproducible Evaluation experiment plans."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, cast

from evaluation.dataset import DatasetError, file_sha256, load_jsonl
from evaluation.prompt_candidate import (
    PromptCandidateError,
    load_prompt_candidate,
    materialize_prompt_candidate,
)

ExperimentKind = Literal["PROMPT", "MODEL", "GRAPH", "INTEGRATED"]
TrialFailurePolicy = Literal["CONTINUE", "STOP"]
PromptCandidateKind = Literal["CURRENT_PRODUCT_BASELINE", "DRAFT_BUNDLE"]

_PLAN_FIELDS = {
    "schema_version",
    "experiment_id",
    "experiment_kind",
    "product_sha",
    "dataset",
    "candidate_config",
    "prompt_candidate",
    "repetitions",
    "randomization_policy",
    "trial_failure_policy",
    "grader",
    "comparison_group",
    "results_root",
    "notes",
}
_DATASET_FIELDS = {"path", "sha256", "case_ids"}
_ARTIFACT_FIELDS = {"path", "sha256"}
_PROMPT_FIELDS = {
    "kind",
    "candidate_id",
    "path",
    "bundle_hash",
    "product_binding_status",
}
_EXPERIMENT_KINDS = {"PROMPT", "MODEL", "GRAPH", "INTEGRATED"}
_FAILURE_POLICIES = {"CONTINUE", "STOP"}
_PROMPT_KINDS = {"CURRENT_PRODUCT_BASELINE", "DRAFT_BUNDLE"}
_PRODUCT_BINDINGS = {"CURRENT_PRODUCT_BASELINE", "PENDING_DEV_LAUNCH_INTEGRATION"}
_HEX_40 = re.compile(r"[0-9a-f]{40}")
_HEX_64 = re.compile(r"[0-9a-f]{64}")


class ExperimentPlanError(ValueError):
    """Raised when an experiment plan cannot prove its identities and controls."""


@dataclass(frozen=True, slots=True)
class ArtifactIdentity:
    path: Path
    repository_path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class PromptCandidateIdentity:
    kind: PromptCandidateKind
    candidate_id: str
    artifact: ArtifactIdentity
    bundle_hash: str
    materialized_prompt_manifest_hash: str
    product_binding_status: str


@dataclass(frozen=True, slots=True)
class ValidatedExperimentPlan:
    source_path: Path
    repository_root: Path
    experiment_id: str
    experiment_kind: ExperimentKind
    product_sha: str
    dataset: ArtifactIdentity
    case_ids: tuple[str, ...]
    cases: tuple[dict[str, object], ...]
    candidate_config: ArtifactIdentity
    candidate_config_id: str
    candidate_config_payload: dict[str, object]
    fixed_configuration_hash: str
    prompt_candidate: PromptCandidateIdentity
    repetitions: int
    randomization_policy: str
    trial_failure_policy: TrialFailurePolicy
    grader: ArtifactIdentity
    comparison_group: str
    results_root: Path
    notes: str
    unresolved_bindings: tuple[str, ...]
    model_binding_status: str
    dev_split_status: str
    holdout_split_status: str

    @property
    def runnable(self) -> bool:
        return not self.unresolved_bindings

    def result_directory(self) -> Path:
        return self.results_root / self.experiment_id

    def provenance(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "experiment_id": self.experiment_id,
            "experiment_kind": self.experiment_kind,
            "comparison_group": self.comparison_group,
            "product_sha": self.product_sha,
            "dataset": {
                "path": self.dataset.repository_path,
                "sha256": self.dataset.sha256,
                "case_ids": list(self.case_ids),
            },
            "candidate_config": {
                "candidate_id": self.candidate_config_id,
                "path": self.candidate_config.repository_path,
                "sha256": self.candidate_config.sha256,
                "fixed_configuration_hash": self.fixed_configuration_hash,
            },
            "prompt_candidate": {
                "kind": self.prompt_candidate.kind,
                "candidate_id": self.prompt_candidate.candidate_id,
                "path": self.prompt_candidate.artifact.repository_path,
                "bundle_hash": self.prompt_candidate.bundle_hash,
                "materialized_prompt_manifest_hash": (
                    self.prompt_candidate.materialized_prompt_manifest_hash
                ),
                "product_binding_status": self.prompt_candidate.product_binding_status,
            },
            "repetitions": self.repetitions,
            "randomization_policy": self.randomization_policy,
            "trial_failure_policy": self.trial_failure_policy,
            "grader": {
                "path": self.grader.repository_path,
                "sha256": self.grader.sha256,
            },
            "unresolved_bindings": list(self.unresolved_bindings),
            "model_binding_status": self.model_binding_status,
            "dev_split_status": self.dev_split_status,
            "holdout_split_status": self.holdout_split_status,
            "notes": self.notes,
        }


def load_experiment_plan(plan_path: Path, *, repository_root: Path) -> ValidatedExperimentPlan:
    """Validate one plan and every referenced immutable artifact."""

    root = repository_root.resolve()
    source_path = plan_path.resolve()
    payload = _load_object(source_path)
    _require_exact_fields(payload, _PLAN_FIELDS, "ExperimentPlanV1")
    if payload.get("schema_version") != 1:
        raise ExperimentPlanError("ExperimentPlanV1 schema_version must be 1")
    experiment_id = _required_string(payload, "experiment_id")
    experiment_kind = _choice(payload, "experiment_kind", _EXPERIMENT_KINDS, "experiment kind")
    product_sha = _required_string(payload, "product_sha")
    if _HEX_40.fullmatch(product_sha) is None:
        raise ExperimentPlanError("product_sha must be a lowercase 40-character Git SHA")

    dataset_spec = _required_object(payload, "dataset")
    _require_exact_fields(dataset_spec, _DATASET_FIELDS, "dataset")
    dataset = _artifact_identity(dataset_spec, root, "dataset")
    try:
        dataset_rows = load_jsonl(dataset.path)
    except DatasetError as error:
        raise ExperimentPlanError("dataset is invalid") from error
    case_ids = _required_unique_strings(dataset_spec, "case_ids")
    rows_by_id: dict[str, dict[str, object]] = {}
    for row in dataset_rows:
        case_id = row.get("case_id")
        if isinstance(case_id, str):
            rows_by_id[case_id] = row
    missing_cases = sorted(set(case_ids) - set(rows_by_id))
    if missing_cases:
        raise ExperimentPlanError(f"dataset is missing case IDs: {missing_cases}")
    selected_cases = tuple(rows_by_id[case_id] for case_id in case_ids)

    candidate_spec = _required_object(payload, "candidate_config")
    _require_exact_fields(candidate_spec, _ARTIFACT_FIELDS, "candidate_config")
    candidate_config = _artifact_identity(candidate_spec, root, "candidate_config")
    candidate_payload = _load_object(candidate_config.path)
    candidate_config_id = _required_string(candidate_payload, "candidate_id")
    runnable = candidate_payload.get("runnable")
    if not isinstance(runnable, bool):
        raise ExperimentPlanError("candidate config runnable must be boolean")
    unresolved = _optional_string_list(candidate_payload, "unresolved_bindings")
    if runnable and unresolved:
        raise ExperimentPlanError("runnable candidate config cannot have unresolved bindings")

    prompt_candidate = _prompt_candidate_identity(
        _required_object(payload, "prompt_candidate"), root
    )
    repetitions = _required_int(payload, "repetitions")
    if repetitions < 1:
        raise ExperimentPlanError("repetitions must be at least 1")
    randomization_policy = _required_string(payload, "randomization_policy")
    if randomization_policy != "CASE_MAJOR":
        raise ExperimentPlanError("randomization_policy must be CASE_MAJOR in scaffold v1")
    trial_failure_policy = _choice(
        payload, "trial_failure_policy", _FAILURE_POLICIES, "trial failure policy"
    )

    grader_spec = _required_object(payload, "grader")
    _require_exact_fields(grader_spec, _ARTIFACT_FIELDS, "grader")
    grader = _artifact_identity(grader_spec, root, "grader")
    comparison_group = _required_string(payload, "comparison_group")
    results_root = _repository_path(root, _required_string(payload, "results_root"), "results_root")
    canonical_results_root = (root / "evaluation/results").resolve()
    if results_root != canonical_results_root:
        raise ExperimentPlanError("results_root must be evaluation/results")
    notes = _required_string(payload, "notes")

    unresolved_bindings = list(unresolved)
    if not runnable:
        unresolved_bindings.append("candidate_config.runnable")
    if prompt_candidate.product_binding_status == "PENDING_DEV_LAUNCH_INTEGRATION":
        unresolved_bindings.append("prompt_candidate.product_binding")
    unresolved_bindings = sorted(set(unresolved_bindings))
    fixed_configuration_hash = _fixed_configuration_hash(candidate_payload)
    split_values = {row.get("split") for row in selected_cases if isinstance(row.get("split"), str)}
    dev_status = "AVAILABLE" if "DEV" in split_values else "NEEDS_DATASET_DECISION"
    holdout_status = "AVAILABLE" if "HOLDOUT" in split_values else "NEEDS_DATASET_DECISION"

    return ValidatedExperimentPlan(
        source_path=source_path,
        repository_root=root,
        experiment_id=experiment_id,
        experiment_kind=cast(ExperimentKind, experiment_kind),
        product_sha=product_sha,
        dataset=dataset,
        case_ids=tuple(case_ids),
        cases=selected_cases,
        candidate_config=candidate_config,
        candidate_config_id=candidate_config_id,
        candidate_config_payload=candidate_payload,
        fixed_configuration_hash=fixed_configuration_hash,
        prompt_candidate=prompt_candidate,
        repetitions=repetitions,
        randomization_policy=randomization_policy,
        trial_failure_policy=cast(TrialFailurePolicy, trial_failure_policy),
        grader=grader,
        comparison_group=comparison_group,
        results_root=results_root,
        notes=notes,
        unresolved_bindings=tuple(unresolved_bindings),
        model_binding_status="READY" if runnable and not unresolved else "PENDING",
        dev_split_status=dev_status,
        holdout_split_status=holdout_status,
    )


def validate_only_report(plan: ValidatedExperimentPlan) -> dict[str, object]:
    return {
        "schema_version": 1,
        "experiment_id": plan.experiment_id,
        "experiment_plan_validation": "PASS",
        "prompt_candidate_id": plan.prompt_candidate.candidate_id,
        "prompt_candidate_bundle_hash": plan.prompt_candidate.bundle_hash,
        "materialized_prompt_manifest_hash": (
            plan.prompt_candidate.materialized_prompt_manifest_hash
        ),
        "case_count": len(plan.case_ids),
        "repetitions": plan.repetitions,
        "expected_trials": len(plan.case_ids) * plan.repetitions,
        "runtime_binding_status": "READY" if plan.runnable else "PENDING",
        "unresolved_bindings": list(plan.unresolved_bindings),
        "model_binding_status": plan.model_binding_status,
        "prompt_candidate_product_binding": plan.prompt_candidate.product_binding_status,
        "dev_split_status": plan.dev_split_status,
        "holdout_split_status": plan.holdout_split_status,
    }


def _prompt_candidate_identity(payload: dict[str, object], root: Path) -> PromptCandidateIdentity:
    _require_exact_fields(payload, _PROMPT_FIELDS, "prompt_candidate")
    kind = _choice(payload, "kind", _PROMPT_KINDS, "Prompt candidate kind")
    candidate_id = _required_string(payload, "candidate_id")
    bundle_hash = _required_digest(payload, "bundle_hash")
    product_binding = _required_string(payload, "product_binding_status")
    if product_binding not in _PRODUCT_BINDINGS:
        raise ExperimentPlanError("unknown Prompt candidate product binding status")
    path = _repository_path(root, _required_string(payload, "path"), "prompt_candidate.path")
    repository_path = path.relative_to(root).as_posix()
    if kind == "CURRENT_PRODUCT_BASELINE":
        if product_binding != "CURRENT_PRODUCT_BASELINE":
            raise ExperimentPlanError("baseline Prompt candidate must use current Product binding")
        actual_hash = file_sha256(path)
        if actual_hash != bundle_hash:
            raise ExperimentPlanError("baseline Prompt bundle hash mismatch")
        materialized_hash = actual_hash
        artifact_hash = actual_hash
    else:
        if product_binding != "PENDING_DEV_LAUNCH_INTEGRATION":
            raise ExperimentPlanError("DRAFT candidate must remain pending Product binding")
        try:
            bundle = load_prompt_candidate(path, repository_root=root)
            with TemporaryDirectory(prefix="gwa-prompt-candidate-") as temporary:
                materialized = materialize_prompt_candidate(
                    candidate_path=path,
                    repository_root=root,
                    output_dir=Path(temporary) / "materialized",
                )
        except PromptCandidateError as error:
            raise ExperimentPlanError("Prompt candidate is invalid") from error
        if bundle.candidate_id != candidate_id or bundle.candidate_bundle_hash != bundle_hash:
            raise ExperimentPlanError("Prompt candidate identity mismatch")
        materialized_hash = materialized.prompt_manifest_hash
        artifact_hash = file_sha256(path)
    return PromptCandidateIdentity(
        kind=cast(PromptCandidateKind, kind),
        candidate_id=candidate_id,
        artifact=ArtifactIdentity(path, repository_path, artifact_hash),
        bundle_hash=bundle_hash,
        materialized_prompt_manifest_hash=materialized_hash,
        product_binding_status=product_binding,
    )


def _fixed_configuration_hash(payload: dict[str, object]) -> str:
    excluded = {
        "candidate_id",
        "candidate_kind",
        "candidate_config_hash",
        "prompt_bundle_version",
        "prompt_overrides",
    }
    fixed = {key: value for key, value in payload.items() if key not in excluded}
    encoded = json.dumps(fixed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _artifact_identity(payload: dict[str, object], root: Path, label: str) -> ArtifactIdentity:
    repository_path = _required_string(payload, "path")
    path = _repository_path(root, repository_path, label)
    expected_hash = _required_digest(payload, "sha256")
    try:
        actual_hash = file_sha256(path)
    except DatasetError as error:
        raise ExperimentPlanError(f"{label} is unavailable") from error
    if actual_hash != expected_hash:
        raise ExperimentPlanError(f"{label} hash mismatch")
    return ArtifactIdentity(path, Path(repository_path).as_posix(), actual_hash)


def _repository_path(root: Path, relative: str, label: str) -> Path:
    path = Path(relative)
    if path.is_absolute():
        raise ExperimentPlanError(f"{label} path must be repository-relative")
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ExperimentPlanError(f"{label} path escapes repository root") from error
    return resolved


def _load_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExperimentPlanError(f"cannot load JSON object: {path}") from error
    if not isinstance(value, dict):
        raise ExperimentPlanError(f"expected JSON object: {path}")
    return cast(dict[str, object], value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ExperimentPlanError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _require_exact_fields(payload: dict[str, object], expected: set[str], label: str) -> None:
    if set(payload) != expected:
        raise ExperimentPlanError(
            f"{label} fields mismatch: missing={sorted(expected - set(payload))}, "
            f"extra={sorted(set(payload) - expected)}"
        )


def _required_object(payload: dict[str, object], field: str) -> dict[str, object]:
    value = payload.get(field)
    if not isinstance(value, dict):
        raise ExperimentPlanError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _required_string(payload: dict[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise ExperimentPlanError(f"{field} must be a non-empty string")
    return value


def _required_digest(payload: dict[str, object], field: str) -> str:
    value = _required_string(payload, field)
    if _HEX_64.fullmatch(value) is None:
        raise ExperimentPlanError(f"{field} must be a lowercase SHA-256")
    return value


def _required_int(payload: dict[str, object], field: str) -> int:
    value = payload.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ExperimentPlanError(f"{field} must be an integer")
    return value


def _required_unique_strings(payload: dict[str, object], field: str) -> list[str]:
    value = payload.get(field)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise ExperimentPlanError(f"{field} must be a non-empty string array")
    result = cast(list[str], value)
    if len(result) != len(set(result)):
        raise ExperimentPlanError(f"{field} contains duplicates")
    return result


def _optional_string_list(payload: dict[str, object], field: str) -> list[str]:
    value = payload.get(field, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ExperimentPlanError(f"{field} must be a string array")
    return cast(list[str], value)


def _choice(payload: dict[str, object], field: str, choices: set[str], label: str) -> str:
    value = _required_string(payload, field)
    if value not in choices:
        raise ExperimentPlanError(f"unknown {label}: {value}")
    return value


__all__ = [
    "ArtifactIdentity",
    "ExperimentPlanError",
    "PromptCandidateIdentity",
    "ValidatedExperimentPlan",
    "load_experiment_plan",
    "validate_only_report",
]
