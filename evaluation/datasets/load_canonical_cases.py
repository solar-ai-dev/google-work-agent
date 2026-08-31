"""Strict deterministic CanonicalCaseV7 JSONL loader."""

from __future__ import annotations

from pathlib import Path

from evaluation.contracts.canonical_case import CanonicalCaseV7
from evaluation.contracts.evaluation_contract import load_strict_json

DEFAULT_CANONICAL_CASES_PATH = Path(__file__).with_name("canonical_cases_v7.jsonl")


class CanonicalCaseDatasetError(ValueError):
    """Raised when the current canonical case dataset is malformed or unsafe."""


def load_canonical_cases(
    path: Path = DEFAULT_CANONICAL_CASES_PATH,
) -> tuple[CanonicalCaseV7, ...]:
    """Load a strictly ordered, duplicate-free current CanonicalCaseV7 dataset."""

    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise CanonicalCaseDatasetError(f"cannot read strict UTF-8 dataset: {path}") from error
    if text.startswith("\ufeff"):
        raise CanonicalCaseDatasetError("UTF-8 BOM is not allowed")
    if not text:
        raise CanonicalCaseDatasetError("canonical case dataset must not be empty")

    cases: list[CanonicalCaseV7] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise CanonicalCaseDatasetError(f"blank JSONL row at line {line_number}")
        try:
            payload = load_strict_json(line)
            case = CanonicalCaseV7.model_validate(payload, strict=True)
        except ValueError as error:
            raise CanonicalCaseDatasetError(
                f"invalid CanonicalCaseV7 at line {line_number}: {error}"
            ) from error
        cases.append(case)

    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise CanonicalCaseDatasetError("duplicate case_id")
    prompt_ids = [case.user_prompt_id for case in cases]
    if len(prompt_ids) != len(set(prompt_ids)):
        raise CanonicalCaseDatasetError("duplicate user_prompt_id")
    if case_ids != sorted(case_ids):
        raise CanonicalCaseDatasetError("rows must be ordered by case_id")

    _validate_split_isolation(cases)
    return tuple(cases)


def _validate_split_isolation(cases: list[CanonicalCaseV7]) -> None:
    scenario_splits: dict[str, set[str]] = {}
    fixture_splits: dict[str, set[str]] = {}
    for case in cases:
        scenario_splits.setdefault(case.scenario_family_id, set()).add(case.split)
        fixture_splits.setdefault(case.fixture_relation_family, set()).add(case.split)
    scenario_leaks = {
        family: sorted(splits) for family, splits in scenario_splits.items() if len(splits) > 1
    }
    if scenario_leaks:
        raise CanonicalCaseDatasetError(f"scenario family split leakage: {scenario_leaks}")
    fixture_leaks = {
        family: sorted(splits)
        for family, splits in fixture_splits.items()
        if "HOLDOUT" in splits and len(splits) > 1
    }
    if fixture_leaks:
        raise CanonicalCaseDatasetError(f"fixture family holdout leakage: {fixture_leaks}")


__all__ = [
    "CanonicalCaseDatasetError",
    "DEFAULT_CANONICAL_CASES_PATH",
    "load_canonical_cases",
]
