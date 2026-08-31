from __future__ import annotations

from pathlib import Path

from evaluation.compat.materialize_current_dataset import materialize_current_dataset


def test_preserved_v7_inputs_reproduce_current_artifacts(tmp_path: Path) -> None:
    dataset_path = tmp_path / "datasets" / "canonical_cases_v7.jsonl"
    micro_root = tmp_path / "datasets" / "micro"
    projection_root = tmp_path / "projections" / "data"

    counts = materialize_current_dataset(
        dataset_path=dataset_path,
        micro_root=micro_root,
        projection_root=projection_root,
    )

    assert counts == (92, 10)
    assert (
        dataset_path.read_bytes()
        == Path("evaluation/datasets/canonical_cases_v7.jsonl").read_bytes()
    )
    assert (projection_root / "e2e_projection_v5.jsonl").read_bytes() == Path(
        "evaluation/projections/data/e2e_projection_v5.jsonl"
    ).read_bytes()
    assert (projection_root / "product_episode_e2e_projection_v1.jsonl").read_bytes() == Path(
        "evaluation/projections/data/product_episode_e2e_projection_v1.jsonl"
    ).read_bytes()
    assert {path.name for path in micro_root.glob("*.jsonl")} == {
        path.name for path in Path("evaluation/datasets/micro").glob("*.jsonl")
    }
