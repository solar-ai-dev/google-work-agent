"""Small, strict helpers for version-controlled evaluation datasets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

CANONICAL_CASES_PATH = Path(__file__).parent / "datasets" / "e2e" / "canonical_cases_v7.jsonl"


class DatasetError(ValueError):
    """Raised when an evaluation dataset is malformed or ambiguous."""


def load_jsonl(path: Path) -> list[dict[str, object]]:
    """Load object-only JSON Lines while rejecting duplicate keys and IDs."""

    rows: list[dict[str, object]] = []
    identifiers: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise DatasetError(f"cannot read dataset: {path}") from error
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line, object_pairs_hook=_unique_object)
        except json.JSONDecodeError as error:
            raise DatasetError(f"invalid JSON at {path}:{line_number}") from error
        if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
            raise DatasetError(f"dataset row must be an object at {path}:{line_number}")
        row = cast(dict[str, object], value)
        identifier = _row_identifier(row)
        if identifier is not None:
            if identifier in identifiers:
                raise DatasetError(f"duplicate dataset identifier: {identifier}")
            identifiers.add(identifier)
        rows.append(row)
    if not rows:
        raise DatasetError(f"dataset is empty: {path}")
    return rows


def load_case(case_id: str, path: Path = CANONICAL_CASES_PATH) -> dict[str, object]:
    """Return one exact case without deriving behavior from Product code."""

    matches = [row for row in load_jsonl(path) if row.get("case_id") == case_id]
    if len(matches) != 1:
        raise DatasetError(f"expected one case_id={case_id}, found {len(matches)}")
    return matches[0]


def file_sha256(path: Path) -> str:
    """Return the byte-level dataset/config identity used in result metadata."""

    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise DatasetError(f"cannot hash artifact: {path}") from error


def _row_identifier(row: dict[str, object]) -> str | None:
    for key in (
        "micro_case_id",
        "runtime_item_id",
        "evaluation_item_id",
        "paraphrase_id",
        "user_prompt_id",
        "case_id",
    ):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DatasetError(f"duplicate JSON key: {key}")
        result[key] = value
    return result
