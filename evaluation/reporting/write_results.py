"""Single atomic writer for the exact twelve current Evaluation result files."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Literal, cast

from pydantic import JsonValue, field_validator, model_validator

from evaluation.contracts.evaluation_contract import EvaluationContract

RESULT_FILENAMES = (
    "experiment_manifest.json",
    "candidate_config.json",
    "config_diff.json",
    "evaluation_items.jsonl",
    "node_results.jsonl",
    "trajectory_results.jsonl",
    "grader_results.jsonl",
    "case_failures.jsonl",
    "summary_metrics.json",
    "budget_report.json",
    "human_review.md",
    "product_decision_record.md",
)
JSON_FILENAMES = {
    "experiment_manifest.json",
    "candidate_config.json",
    "config_diff.json",
    "summary_metrics.json",
    "budget_report.json",
}
JSONL_FILENAMES = {
    "evaluation_items.jsonl",
    "node_results.jsonl",
    "trajectory_results.jsonl",
    "grader_results.jsonl",
    "case_failures.jsonl",
}
_SENSITIVE_KEYS = {
    "access_token",
    "refresh_token",
    "api_key",
    "password",
    "secret",
    "credential",
    "credentials",
    "authorization",
    "cookie",
    "client_secret",
    "private_key",
    "oauth_token",
    "id_token",
    "raw_provider_payload",
    "raw_user_data",
    "prompt_text",
    "completion_text",
}


class ResultWriteError(ValueError):
    """Raised when a result set is incomplete, unsafe, or would overwrite history."""


class EvaluationResultSetV1(EvaluationContract):
    schema_version: Literal[1]
    experiment_manifest: dict[str, JsonValue]
    candidate_config: dict[str, JsonValue]
    config_diff: dict[str, JsonValue]
    evaluation_items: list[dict[str, JsonValue]]
    node_results: list[dict[str, JsonValue]]
    trajectory_results: list[dict[str, JsonValue]]
    grader_results: list[dict[str, JsonValue]]
    case_failures: list[dict[str, JsonValue]]
    summary_metrics: dict[str, JsonValue]
    budget_report: dict[str, JsonValue]
    human_review: str
    product_decision_record: str

    @field_validator("human_review", "product_decision_record")
    @classmethod
    def _require_markdown(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("markdown result artifacts must be non-empty")
        return value

    @model_validator(mode="after")
    def _reject_false_complete_status(self) -> EvaluationResultSetV1:
        status = self.experiment_manifest.get("run_status")
        if status not in {"COMPLETE", "PARTIAL"}:
            raise ValueError("experiment_manifest.run_status must be COMPLETE or PARTIAL")
        expected = self.experiment_manifest.get("evaluation_item_count")
        completed = self.experiment_manifest.get("completed_item_count")
        if status == "COMPLETE" and (not isinstance(expected, int) or completed != expected):
            raise ValueError("a COMPLETE result must account for every evaluation item")
        return self


def write_results(
    *,
    experiment_id: str,
    result_set: EvaluationResultSetV1,
    results_root: Path,
) -> Path:
    """Atomically write one non-overwriting, sanitized twelve-file result set."""

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", experiment_id):
        raise ResultWriteError("invalid experiment_id")
    manifest_id = result_set.experiment_manifest.get("experiment_id")
    if manifest_id != experiment_id:
        raise ResultWriteError("experiment_id does not match the manifest")
    _reject_sensitive_payload(result_set.model_dump(mode="json"))

    results_root.mkdir(parents=True, exist_ok=True)
    target = results_root / experiment_id
    lock = results_root / f".{experiment_id}.lock"
    try:
        lock_descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise ResultWriteError(f"result write is already in progress: {target}") from error
    os.close(lock_descriptor)
    temp = results_root / f".{experiment_id}.{uuid.uuid4().hex}.tmp"
    try:
        if target.exists():
            raise ResultWriteError(f"result directory already exists: {target}")
        temp.mkdir(parents=False, exist_ok=False)
        serialized = _serialize_without_manifest(result_set)
        artifact_hashes = {
            filename: hashlib.sha256(payload).hexdigest()
            for filename, payload in serialized.items()
        }
        manifest = dict(result_set.experiment_manifest)
        manifest["artifact_hashes"] = cast(JsonValue, artifact_hashes)
        serialized["experiment_manifest.json"] = _json_bytes(manifest)
        if set(serialized) != set(RESULT_FILENAMES):
            raise ResultWriteError("result writer did not materialize the exact required set")
        for filename in RESULT_FILENAMES:
            (temp / filename).write_bytes(serialized[filename])
        os.replace(temp, target)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    finally:
        lock.unlink(missing_ok=True)
    return target


def _serialize_without_manifest(result_set: EvaluationResultSetV1) -> dict[str, bytes]:
    values = result_set.model_dump(mode="json")
    serialized: dict[str, bytes] = {}
    field_by_filename = {
        "candidate_config.json": "candidate_config",
        "config_diff.json": "config_diff",
        "evaluation_items.jsonl": "evaluation_items",
        "node_results.jsonl": "node_results",
        "trajectory_results.jsonl": "trajectory_results",
        "grader_results.jsonl": "grader_results",
        "case_failures.jsonl": "case_failures",
        "summary_metrics.json": "summary_metrics",
        "budget_report.json": "budget_report",
        "human_review.md": "human_review",
        "product_decision_record.md": "product_decision_record",
    }
    for filename, field in field_by_filename.items():
        value = values[field]
        if filename in JSON_FILENAMES:
            serialized[filename] = _json_bytes(value)
        elif filename in JSONL_FILENAMES:
            if not isinstance(value, list):
                raise ResultWriteError(f"{filename} must serialize from a row array")
            serialized[filename] = _jsonl_bytes(value)
        else:
            if not isinstance(value, str):
                raise ResultWriteError(f"{filename} must be markdown text")
            serialized[filename] = (value.rstrip() + "\n").encode("utf-8")
    return serialized


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _jsonl_bytes(rows: list[object]) -> bytes:
    if not rows:
        return b""
    payload = "\n".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True) for row in rows
    )
    return (payload + "\n").encode("utf-8")


def _reject_sensitive_payload(value: object, path: str = "result_set") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower()
            if normalized in _SENSITIVE_KEYS:
                raise ResultWriteError(f"sensitive field is forbidden: {path}.{key}")
            _reject_sensitive_payload(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_sensitive_payload(nested, f"{path}[{index}]")
    elif isinstance(value, str) and ("Bearer " in value or "-----BEGIN PRIVATE KEY-----" in value):
        raise ResultWriteError(f"sensitive value is forbidden: {path}")


__all__ = [
    "EvaluationResultSetV1",
    "RESULT_FILENAMES",
    "ResultWriteError",
    "write_results",
]
