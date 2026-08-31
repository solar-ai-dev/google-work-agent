"""Deterministically materialize current bounded Evaluation projections."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pydantic import JsonValue, ValidationError

from evaluation.contracts.canonical_case import CanonicalCaseV7
from evaluation.contracts.e2e_projection import E2EProjectionV5
from evaluation.contracts.evaluation_contract import EvaluationContract, load_strict_json
from evaluation.contracts.product_episode_projection import ProductEpisodeE2EProjectionV1
from evaluation.datasets.load_canonical_cases import load_canonical_cases

DEFAULT_PROJECTION_DATA_DIR = Path(__file__).with_name("data")
E2E_PROJECTION_FILENAME = "e2e_projection_v5.jsonl"
PRODUCT_EPISODE_PROJECTION_FILENAME = "product_episode_e2e_projection_v1.jsonl"


class ProjectionBuildError(ValueError):
    """Raised when current projections cannot be safely materialized."""


@dataclass(frozen=True, slots=True)
class ProjectionBuildResult:
    e2e_path: Path
    product_episode_path: Path
    e2e_count: int
    product_episode_count: int


def build_current_projections(
    *,
    cases: Iterable[CanonicalCaseV7] | None = None,
    product_episodes: Iterable[ProductEpisodeE2EProjectionV1] | None = None,
    output_dir: Path = DEFAULT_PROJECTION_DATA_DIR,
) -> ProjectionBuildResult:
    """Write the exact current E2E and Product Episode JSONL projections."""

    ordered_cases = sorted(cases or load_canonical_cases(), key=lambda item: item.case_id)
    dataset_hash = hashlib.sha256(
        ("\n".join(case.canonical_json() for case in ordered_cases) + "\n").encode("utf-8")
    ).hexdigest()
    e2e_rows = [_project_case(case, dataset_hash=dataset_hash) for case in ordered_cases]
    e2e_ids = [row.case_id for row in e2e_rows]
    if len(e2e_ids) != len(set(e2e_ids)):
        raise ProjectionBuildError("duplicate E2E projection case_id")

    episode_path = output_dir / PRODUCT_EPISODE_PROJECTION_FILENAME
    if product_episodes is None:
        episode_rows = _load_existing_product_episodes(episode_path)
    else:
        episode_rows = sorted(product_episodes, key=lambda item: item.case_id)
    episode_ids = [row.case_id for row in episode_rows]
    if len(episode_ids) != len(set(episode_ids)):
        raise ProjectionBuildError("duplicate Product Episode projection case_id")

    output_dir.mkdir(parents=True, exist_ok=True)
    e2e_path = output_dir / E2E_PROJECTION_FILENAME
    _write_jsonl_atomic(e2e_path, e2e_rows)
    _write_jsonl_atomic(episode_path, episode_rows)
    return ProjectionBuildResult(
        e2e_path=e2e_path,
        product_episode_path=episode_path,
        e2e_count=len(e2e_rows),
        product_episode_count=len(episode_rows),
    )


def _project_case(case: CanonicalCaseV7, *, dataset_hash: str | None = None) -> E2EProjectionV5:
    resolved_dataset_hash = (
        dataset_hash or hashlib.sha256((case.canonical_json() + "\n").encode("utf-8")).hexdigest()
    )
    runtime_item_id = (
        "item_"
        + hashlib.sha256(f"{resolved_dataset_hash}:{case.case_id}".encode()).hexdigest()[:24]
    )
    product_input = {
        "schema_version": 1,
        "runtime_item_id": runtime_item_id,
        "fixture_snapshot_id": case.fixture_snapshot_id,
        "entry_mode": case.entry_mode,
        "user_prompt": case.canonical_user_prompt,
        "selected_resource_handles": case.selected_resource_handles,
    }
    return E2EProjectionV5(
        schema_version=5,
        case_id=case.case_id,
        runtime_item_id=runtime_item_id,
        source_dataset_hash=resolved_dataset_hash,
        fixture_snapshot_id=case.fixture_snapshot_id,
        product_input=_json_value(product_input),
        business_gold=_json_value(
            {
                "expected_goal": case.expected_goal,
                "expected_completion_criteria": case.expected_completion_criteria,
                "requested_outcome": case.requested_outcome,
                "required_resource_ids": case.required_resource_ids,
                "hard_negative_resource_ids": case.hard_negative_resource_ids,
                "required_evidence_ids": case.required_evidence_ids,
            }
        ),
        request_gold=_json_value(
            {
                "expected_goal": case.expected_goal,
                "expected_completion_criteria": case.expected_completion_criteria,
            }
        ),
        interaction_gold=case.expected_interactions,
        tool_route_gold=_json_value(
            {
                "expected_input_route_plan": case.expected_input_route_plan,
                "expected_output_plan": case.expected_output_plan,
                "required_input_routes": case.required_input_routes,
                "optional_input_routes": case.optional_input_routes,
                "forbidden_input_routes": case.forbidden_input_routes,
                "required_output_routes": case.required_output_routes,
                "forbidden_output_routes": case.forbidden_output_routes,
            }
        ),
        retrieval_gold=case.expected_retrieval_trajectory,
        analysis_gold=_json_value({"node_applicability": case.node_applicability}),
        planning_gold=_json_value(
            {
                "result_type": case.expected_planning_result_type,
                "allowed_actions": case.allowed_actions,
            }
        ),
        review_gold=_json_value({"human_rubric": case.human_rubric}),
        workflow_gold=_json_value(
            {
                "run_outcome_expectation": case.run_outcome_expectation,
                "semantic_milestones": case.expected_semantic_milestones,
                "six_reference_route": case.six_reference_route,
                "six_reference_skipped_nodes": case.six_reference_skipped_nodes,
                "expected_tool_trajectory": case.expected_tool_trajectory,
            }
        ),
        safety_gold=_json_value(
            {
                "policy_result": case.policy_result,
                "approval_expectation": case.approval_expectation,
                "verification_expectation": case.verification_expectation,
                "forbidden_actions": case.forbidden_actions,
            }
        ),
        end_state_gold=case.end_state_gold,
    )


def _load_existing_product_episodes(path: Path) -> list[ProductEpisodeE2EProjectionV1]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ProjectionBuildError(
            "product_episodes must be supplied when no current projection file exists"
        ) from error
    rows: list[ProductEpisodeE2EProjectionV1] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise ProjectionBuildError(f"blank Product Episode row at line {line_number}")
        try:
            payload = load_strict_json(line)
            rows.append(ProductEpisodeE2EProjectionV1.model_validate(payload, strict=True))
        except (ValueError, ValidationError) as error:
            raise ProjectionBuildError(
                f"invalid Product Episode projection at line {line_number}: {error}"
            ) from error
    return sorted(rows, key=lambda item: item.case_id)


def _write_jsonl_atomic(path: Path, rows: Iterable[EvaluationContract]) -> None:
    temp_path = path.with_name(f".{path.name}.tmp")
    serialized: list[str] = []
    for row in rows:
        serialized.append(row.canonical_json())
    payload = "\n".join(serialized) + "\n"
    try:
        temp_path.write_text(payload, encoding="utf-8", newline="\n")
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _json_value(value: object) -> JsonValue:
    return cast(JsonValue, value)


__all__ = [
    "DEFAULT_PROJECTION_DATA_DIR",
    "ProjectionBuildError",
    "ProjectionBuildResult",
    "build_current_projections",
]
