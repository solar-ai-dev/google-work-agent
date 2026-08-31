from __future__ import annotations

import json
from pathlib import Path

from evaluation.datasets.load_canonical_cases import load_canonical_cases

MICRO_ROOT = Path("evaluation/datasets/micro")
EXPECTED_IDS = {
    "resource_selected_variants",
    "review_challenges",
    "structured_output_repair",
    "fault_profiles",
    "injection_variants",
    "paraphrase_robustness",
}
EXPECTED_COUNTS = {
    "resource_selected_variants": 8,
    "review_challenges": 32,
    "structured_output_repair": 24,
    "fault_profiles": 18,
    "injection_variants": 12,
    "paraphrase_robustness": 40,
}


def test_micro_dataset_exact_set_and_current_case_lineage() -> None:
    files = {path.stem: path for path in MICRO_ROOT.glob("*.jsonl")}
    cases = {case.case_id: case for case in load_canonical_cases()}

    assert set(files) == EXPECTED_IDS
    seen_micro_ids: set[str] = set()
    for dataset_id, path in files.items():
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == EXPECTED_COUNTS[dataset_id]
        for row in rows:
            assert set(row) == {
                "schema_version",
                "dataset_id",
                "micro_case_id",
                "case_id",
                "partition",
                "scenario_family_id",
                "fixture_relation_family",
                "source_case_hash",
                "input",
                "expected",
            }
            assert row["schema_version"] == 1
            assert row["dataset_id"] == dataset_id
            assert row["partition"] in {"DEV", "SAFETY"}
            assert row["case_id"] in cases
            assert row["source_case_hash"] == cases[row["case_id"]].stable_hash()
            assert row["micro_case_id"] not in seen_micro_ids
            assert isinstance(row["input"], dict) and row["input"]
            assert isinstance(row["expected"], dict) and row["expected"]
            seen_micro_ids.add(row["micro_case_id"])

    paraphrases = [
        json.loads(line)
        for line in files["paraphrase_robustness"].read_text(encoding="utf-8").splitlines()
    ]
    assert {row["input"]["language"] for row in paraphrases} == {"ko-KR", "en-US"}
    assert all(row["input"]["text"].strip() for row in paraphrases)


def test_micro_datasets_do_not_consume_holdout_cases() -> None:
    holdout_ids = {case.case_id for case in load_canonical_cases() if case.split == "HOLDOUT"}
    micro_case_refs = {
        json.loads(line)["case_id"]
        for path in MICRO_ROOT.glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    }

    assert micro_case_refs.isdisjoint(holdout_ids)
