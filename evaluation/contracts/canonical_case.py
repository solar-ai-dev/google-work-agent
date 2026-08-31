"""CanonicalCaseV7 and EndStateGoldV1 Evaluation contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import JsonValue, field_validator, model_validator

from evaluation.contracts.evaluation_contract import EvaluationContract


class EndStateGoldV1(EvaluationContract):
    schema_version: Literal[1]
    initial_fixture_snapshot_id: str
    completion_mode: Literal["COMPLETE", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED"]
    expected_mutations: list[JsonValue]
    indeterminate_mutations: list[JsonValue]
    forbidden_mutations: list[JsonValue]
    terminal_expectation: Literal["COMPLETED", "BLOCKED", "FAILED", "CANCELLED"]

    @field_validator("initial_fixture_snapshot_id")
    @classmethod
    def _require_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("initial_fixture_snapshot_id must be non-empty")
        return value


class CanonicalCaseV7(EvaluationContract):
    schema_version: Literal[7]
    case_id: str
    scenario_family_id: str
    fixture_relation_family: str
    split: Literal["CORE", "HOLDOUT", "STRESS"]
    dataset_version: str
    category: str
    language: str
    entry_mode: str
    user_prompt_id: str
    canonical_user_prompt: str
    fixture_snapshot_id: str
    expected_goal: str
    expected_completion_criteria: list[str]
    requested_outcome: str
    selected_resource_handles: list[str]
    required_input_routes: list[JsonValue]
    optional_input_routes: list[JsonValue]
    forbidden_input_routes: list[JsonValue]
    required_output_routes: list[JsonValue]
    forbidden_output_routes: list[JsonValue]
    required_resource_ids: list[str]
    hard_negative_resource_ids: list[str]
    required_evidence_ids: list[str]
    user_evidence: list[JsonValue]
    derived_evidence: list[JsonValue]
    expected_input_route_plan: JsonValue
    expected_output_plan: JsonValue
    expected_retrieval_trajectory: JsonValue
    expected_tool_trajectory: JsonValue
    policy_result: JsonValue
    allowed_actions: list[JsonValue]
    forbidden_actions: list[JsonValue]
    approval_expectation: JsonValue
    verification_expectation: dict[str, JsonValue]
    run_outcome_expectation: JsonValue
    expected_planning_result_type: str
    expected_interactions: list[JsonValue]
    expected_semantic_milestones: list[JsonValue]
    six_reference_route: list[str]
    six_reference_skipped_nodes: list[str]
    node_applicability: dict[str, bool]
    human_rubric: JsonValue
    end_state_gold: EndStateGoldV1

    @field_validator(
        "case_id",
        "scenario_family_id",
        "fixture_relation_family",
        "dataset_version",
        "category",
        "language",
        "entry_mode",
        "user_prompt_id",
        "canonical_user_prompt",
        "fixture_snapshot_id",
        "expected_goal",
        "requested_outcome",
        "expected_planning_result_type",
    )
    @classmethod
    def _require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("identity and semantic text fields must be non-empty")
        return value

    @model_validator(mode="after")
    def _reject_gold_overlap(self) -> CanonicalCaseV7:
        required_resources = set(self.required_resource_ids)
        hard_negatives = set(self.hard_negative_resource_ids)
        overlap = required_resources & hard_negatives
        if overlap:
            raise ValueError(f"required and hard-negative resources overlap: {sorted(overlap)}")
        return self
