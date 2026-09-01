from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from evaluation.datasets.load_canonical_cases import (
    CanonicalCaseDatasetError,
    load_canonical_cases,
)
from tests.support.evaluation_case import make_case


def test_current_canonical_cases_are_exact_deterministic_92_case_set() -> None:
    cases = load_canonical_cases()

    assert len(cases) == 92
    assert Counter(case.split for case in cases) == {
        "CORE": 60,
        "HOLDOUT": 12,
        "STRESS": 20,
    }
    assert [case.case_id for case in cases] == sorted(case.case_id for case in cases)
    assert len({case.stable_hash() for case in cases}) == 92


def test_loader_rejects_duplicate_malformed_wrong_version_and_unsorted_rows(
    tmp_path: Path,
) -> None:
    first = make_case("CASE-CORE-001").model_dump(mode="json")
    second = make_case("CASE-CORE-002").model_dump(mode="json")
    second["scenario_family_id"] = "SF-CORE-002"
    second["fixture_relation_family"] = "RF-CORE-002"
    second["user_prompt_id"] = "UP-CASE-CORE-002"
    path = tmp_path / "cases.jsonl"

    path.write_text(json.dumps(first) + "\n" + json.dumps(first) + "\n", encoding="utf-8")
    with pytest.raises(CanonicalCaseDatasetError, match="duplicate case_id"):
        load_canonical_cases(path)

    path.write_text("{not-json}\n", encoding="utf-8")
    with pytest.raises(CanonicalCaseDatasetError, match="invalid CanonicalCaseV7"):
        load_canonical_cases(path)

    wrong_version = dict(first)
    wrong_version["schema_version"] = 6
    path.write_text(json.dumps(wrong_version) + "\n", encoding="utf-8")
    with pytest.raises(CanonicalCaseDatasetError, match="invalid CanonicalCaseV7"):
        load_canonical_cases(path)

    path.write_text(json.dumps(second) + "\n" + json.dumps(first) + "\n", encoding="utf-8")
    with pytest.raises(CanonicalCaseDatasetError, match="ordered by case_id"):
        load_canonical_cases(path)


def test_loader_rejects_holdout_family_leakage(tmp_path: Path) -> None:
    core = make_case("CASE-CORE-001").model_dump(mode="json")
    holdout = make_case("CASE-HOLDOUT-001").model_dump(mode="json")
    holdout["split"] = "HOLDOUT"
    holdout["user_prompt_id"] = "UP-CASE-HOLDOUT-001"
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(core) + "\n" + json.dumps(holdout) + "\n", encoding="utf-8")

    with pytest.raises(CanonicalCaseDatasetError, match="scenario family split leakage"):
        load_canonical_cases(path)


def test_loader_rejects_utf8_bom_and_blank_rows(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_bytes(b"\xef\xbb\xbf{}\n")
    with pytest.raises(CanonicalCaseDatasetError, match="BOM"):
        load_canonical_cases(path)

    path.write_text(make_case().canonical_json() + "\n\n", encoding="utf-8")
    with pytest.raises(CanonicalCaseDatasetError, match="blank JSONL"):
        load_canonical_cases(path)


def test_loader_rejects_duplicate_json_object_keys(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    payload = make_case().canonical_json()
    path.write_text(payload[:-1] + ',"case_id":"ambiguous"}\n', encoding="utf-8")

    with pytest.raises(CanonicalCaseDatasetError, match="duplicate JSON key"):
        load_canonical_cases(path)


def test_rewritten_holdouts_have_independent_semantics_and_fixture_families() -> None:
    cases = load_canonical_cases()
    rewritten = [
        case
        for case in cases
        if case.case_id in {f"CASE-HOLDOUT-{index:03d}" for index in range(3, 11)}
    ]
    dev = [case for case in cases if case.split != "HOLDOUT"]
    assert len(rewritten) == 8
    assert len({case.scenario_family_id for case in rewritten}) == 8
    assert len({case.fixture_relation_family for case in rewritten}) == 8
    assert len({case.fixture_snapshot_id for case in rewritten}) == 8
    assert {case.scenario_family_id for case in rewritten}.isdisjoint(
        {case.scenario_family_id for case in dev}
    )
    assert {case.fixture_relation_family for case in rewritten}.isdisjoint(
        {case.fixture_relation_family for case in dev}
    )
    assert len({case.category for case in rewritten}) == 8


def test_loader_rejects_cross_split_near_duplicate_prompt(tmp_path: Path) -> None:
    core = make_case("CASE-CORE-001").model_dump(mode="json")
    holdout = make_case("CASE-HOLDOUT-001").model_dump(mode="json")
    holdout.update(
        {
            "split": "HOLDOUT",
            "scenario_family_id": "SF-HOLDOUT-UNIQUE",
            "fixture_relation_family": "RF-HOLDOUT-UNIQUE",
            "user_prompt_id": "UP-HOLDOUT-UNIQUE",
            "canonical_user_prompt": core["canonical_user_prompt"] + "!",
        }
    )
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(core) + "\n" + json.dumps(holdout) + "\n", encoding="utf-8")
    with pytest.raises(CanonicalCaseDatasetError, match="near-duplicate"):
        load_canonical_cases(path)
