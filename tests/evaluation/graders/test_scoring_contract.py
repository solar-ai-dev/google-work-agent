from __future__ import annotations

from pathlib import Path

import pytest
from evaluation.graders.grade_item import GraderDispatchError, load_scoring_contract


def test_current_scoring_contract_is_exact_and_supporting_semantic_only() -> None:
    contract = load_scoring_contract()

    assert contract["schema_version"] == "1.1"
    assert contract["grader_registry_version"] == "0.4"
    assert contract["semantic_grader_authority"] == "SUPPORTING_ONLY"
    assert contract["partial_run_counts_as_complete"] is False
    assert contract["selection_order"] == [
        "SAFETY_INTEGRITY_HARD_GATE",
        "BUSINESS_TASK_SUCCESS",
        "PROCESS_DIAGNOSTICS",
        "EFFICIENCY",
        "RELIABILITY",
    ]


def test_scoring_contract_rejects_duplicate_keys_and_wrong_version(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":"1.1","schema_version":"1.1"}', encoding="utf-8")
    with pytest.raises(GraderDispatchError, match="duplicate"):
        load_scoring_contract(duplicate)

    wrong = tmp_path / "wrong.json"
    current = Path("evaluation/graders/scoring-contract-v1.1.json").read_text(encoding="utf-8")
    wrong.write_text(
        current.replace('"schema_version": "1.1"', '"schema_version": "1.0"'),
        encoding="utf-8",
    )
    with pytest.raises(GraderDispatchError, match="incompatible"):
        load_scoring_contract(wrong)
