from __future__ import annotations

from pathlib import Path

from evaluation.contracts.e2e_projection import E2EProjectionV5
from evaluation.contracts.product_episode_projection import ProductEpisodeE2EProjectionV1
from evaluation.datasets.load_canonical_cases import load_canonical_cases
from evaluation.projections.build_current_projections import build_current_projections
from tests.support.evaluation_case import make_case, make_episode


def test_projection_builder_writes_exact_deterministic_gold_isolated_files(
    tmp_path: Path,
) -> None:
    first = build_current_projections(
        cases=[make_case()],
        product_episodes=[make_episode()],
        output_dir=tmp_path,
    )
    first_e2e = first.e2e_path.read_bytes()
    first_episode = first.product_episode_path.read_bytes()
    second = build_current_projections(
        cases=[make_case()],
        product_episodes=[make_episode()],
        output_dir=tmp_path,
    )

    assert first.e2e_count == 1
    assert first.product_episode_count == 1
    assert first_e2e == second.e2e_path.read_bytes()
    assert first_episode == second.product_episode_path.read_bytes()
    assert {path.name for path in tmp_path.iterdir()} == {
        "e2e_projection_v5.jsonl",
        "product_episode_e2e_projection_v1.jsonl",
    }
    e2e = E2EProjectionV5.model_validate_json(
        first.e2e_path.read_text(encoding="utf-8").strip(), strict=True
    )
    episode = ProductEpisodeE2EProjectionV1.model_validate_json(
        first.product_episode_path.read_text(encoding="utf-8").strip(), strict=True
    )
    assert isinstance(e2e.product_input, dict)
    assert isinstance(episode.product_input, dict)
    assert "gold" not in e2e.product_input
    assert "case_id" not in e2e.product_input
    assert e2e.product_input["runtime_item_id"] == e2e.runtime_item_id
    serialized_input = str(e2e.product_input).upper()
    assert all(
        label not in serialized_input
        for label in ("CASE-CORE", "CASE-HOLDOUT", "CASE-STRESS", '"SPLIT"')
    )
    assert "decision_script" not in episode.product_input


def test_current_projection_files_match_current_case_identity_set() -> None:
    e2e_path = Path("evaluation/projections/data/e2e_projection_v5.jsonl")
    episode_path = Path("evaluation/projections/data/product_episode_e2e_projection_v1.jsonl")
    e2e = [
        E2EProjectionV5.model_validate_json(line, strict=True)
        for line in e2e_path.read_text(encoding="utf-8").splitlines()
    ]
    episodes = [
        ProductEpisodeE2EProjectionV1.model_validate_json(line, strict=True)
        for line in episode_path.read_text(encoding="utf-8").splitlines()
    ]

    assert {row.case_id for row in e2e} == {case.case_id for case in load_canonical_cases()}
    assert len(episodes) == 10
