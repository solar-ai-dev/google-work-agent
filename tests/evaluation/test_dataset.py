from __future__ import annotations

import json
from pathlib import Path

import pytest
from evaluation.dataset import DatasetError, load_case, load_jsonl

ROOT = Path(__file__).parents[2]
DATASETS = ROOT / "evaluation" / "datasets"


def test_dataset_inventory_preserves_cases_gold_and_fixture_coverage() -> None:
    canonical = load_jsonl(DATASETS / "e2e" / "canonical_cases_v7.jsonl")
    episodes = load_jsonl(DATASETS / "e2e" / "product_episodes_v1.jsonl")
    node_items = load_jsonl(DATASETS / "agent" / "node_evaluation_items_v1.jsonl")
    micro_paths = sorted(
        path
        for path in (DATASETS / "agent").glob("*.jsonl")
        if path.name != "node_evaluation_items_v1.jsonl"
    ) + [DATASETS / "retrieval" / "resource_selected_variants.jsonl"]
    micro = [row for path in micro_paths for row in load_jsonl(path)]
    prompt_rows = [
        row
        for path in sorted((DATASETS / "agent" / "prompts").glob("*.jsonl"))
        for row in load_jsonl(path)
    ]
    context_items = json.loads(
        (DATASETS / "retrieval" / "CTXREADY-CORE-002" / "evaluation-item.json").read_text(
            encoding="utf-8"
        )
    )
    policy_micro = list((DATASETS / "e2e" / "policy_contract_micro").glob("*.json"))

    assert len(canonical) == 92
    assert {row["split"] for row in canonical} == {"CORE", "STRESS", "HOLDOUT"}
    assert len(episodes) == 10
    assert len(node_items) == 21
    assert len(micro) == 134
    assert len(prompt_rows) == 120
    assert isinstance(context_items, dict)
    assert len(policy_micro) == 4
    assert 92 + 10 + 21 + 134 + 120 + 1 + 4 == 382

    primary_gold_rows = (
        sum("end_state_gold" in row for row in canonical)
        + sum("end_state_gold" in row for row in episodes)
        + sum("expected" in row for row in micro)
        + len(policy_micro)
        + 1
    )
    assert primary_gold_rows == 241

    fixture_ids = {str(row["fixture_snapshot_id"]) for row in canonical + episodes}
    fixture_root = DATASETS / "e2e" / "fixtures" / "google_workspace"
    assert fixture_ids == {path.name for path in fixture_root.iterdir() if path.is_dir()}
    for fixture_id in fixture_ids:
        assert {path.name for path in (fixture_root / fixture_id).glob("*.json")} == {
            "calendar.json",
            "fixture-world.json",
            "gmail.json",
            "relations.json",
            "tasks.json",
        }

    episode_ids = {str(row["case_id"]) for row in episodes}
    gold_ids = {
        str(json.loads(path.read_text(encoding="utf-8"))["variant_id"])
        for path in (DATASETS / "e2e" / "product_episode_gold").glob("*.json")
    }
    assert episode_ids == gold_ids


def test_all_json_and_jsonl_assets_parse_strictly() -> None:
    for path in DATASETS.rglob("*.jsonl"):
        load_jsonl(path)
    for path in DATASETS.rglob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(value, dict | list)


def test_loader_rejects_duplicate_keys_and_duplicate_ids(tmp_path: Path) -> None:
    duplicate_key = tmp_path / "duplicate-key.jsonl"
    duplicate_key.write_text('{"case_id":"A","case_id":"B"}\n', encoding="utf-8")
    with pytest.raises(DatasetError, match="duplicate JSON key"):
        load_jsonl(duplicate_key)

    duplicate_id = tmp_path / "duplicate-id.jsonl"
    duplicate_id.write_text('{"case_id":"A"}\n{"case_id":"A"}\n', encoding="utf-8")
    with pytest.raises(DatasetError, match="duplicate dataset identifier"):
        load_jsonl(duplicate_id)


def test_load_case_resolves_exactly_one_canonical_case() -> None:
    assert load_case("CASE-CORE-001")["case_id"] == "CASE-CORE-001"
    with pytest.raises(DatasetError, match="found 0"):
        load_case("CASE-NOT-PRESENT")
