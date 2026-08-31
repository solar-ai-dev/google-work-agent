"""Closed experiment configuration and target contracts."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import JsonValue, field_validator, model_validator

from evaluation.contracts.evaluation_contract import EvaluationContract


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


class ExperimentTargetV1(EvaluationContract):
    schema_version: Literal[1]
    target_kind: Literal["NODE", "SUBGRAPH", "MAIN_PROFILE"]
    target_id: str

    @field_validator("target_id")
    @classmethod
    def _require_target_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("target_id must be non-empty")
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
    target: ExperimentTargetV1
    upstream_mode: Literal["ORACLE", "LIVE"] | None
    trial_count: int
    grader_version: Literal["0.5"]
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
        payload = json.dumps(
            self.candidate_config,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if self.candidate_config_hash != hashlib.sha256(payload).hexdigest():
            raise ValueError("candidate_config_hash does not match candidate_config")
        return self


__all__ = ["EvaluationBudgetV1", "ExperimentConfigV1", "ExperimentTargetV1"]
