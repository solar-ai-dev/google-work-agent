"""Load and validate one current fixture snapshot without compat imports."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast

from pydantic import JsonValue

from evaluation.contracts.current_fixture_snapshot import CurrentFixtureSnapshotV1
from evaluation.contracts.evaluation_contract import load_strict_json

CURRENT_FIXTURE_ROOT = Path(__file__).with_name("data") / "google_workspace"
_FILES = ("fixture-world.json", "gmail.json", "tasks.json", "calendar.json", "relations.json")


class CurrentFixtureLoadError(ValueError):
    """Raised for missing, malformed, or evaluator-leaking fixture data."""


def current_fixture_root_hash(root: Path = CURRENT_FIXTURE_ROOT) -> str:
    digest = hashlib.sha256()
    files = sorted(root.rglob("*.json"))
    if not files:
        raise CurrentFixtureLoadError("current fixture root has no snapshots")
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def load_current_fixture(
    fixture_snapshot_id: str,
    *,
    root: Path = CURRENT_FIXTURE_ROOT,
) -> CurrentFixtureSnapshotV1:
    directory = root / fixture_snapshot_id
    if not directory.is_dir() or set(path.name for path in directory.glob("*.json")) != set(_FILES):
        raise CurrentFixtureLoadError(
            f"fixture must contain the exact five files: {fixture_snapshot_id}"
        )
    payloads = {name: _object(directory / name) for name in _FILES}
    world = payloads["fixture-world.json"]
    if world.get("fixture_snapshot_id") != fixture_snapshot_id:
        raise CurrentFixtureLoadError("fixture directory and snapshot identity differ")
    forbidden = {"gold", "expected_answer", "grader", "split", "case_id"}
    _reject_evaluator_fields(payloads, forbidden)
    return CurrentFixtureSnapshotV1(
        schema_version=1,
        fixture_snapshot_id=fixture_snapshot_id,
        scenario_family_ids=_string_list(world, "scenario_family_ids"),
        fixture_relation_family=_string(world, "fixture_relation_family"),
        locale=_string(world, "locale"),
        timezone=_string(world, "timezone"),
        as_of=_string(world, "as_of"),
        permissions=cast(dict[str, JsonValue], world.get("permissions", {})),
        tool_availability=cast(list[str], world.get("tool_availability", [])),
        gmail=cast(dict[str, JsonValue], payloads["gmail.json"]),
        tasks=cast(dict[str, JsonValue], payloads["tasks.json"]),
        calendar=cast(dict[str, JsonValue], payloads["calendar.json"]),
        relations=cast(dict[str, JsonValue], payloads["relations.json"]),
    )


def _object(path: Path) -> dict[str, object]:
    try:
        value = load_strict_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise CurrentFixtureLoadError(f"invalid fixture file: {path.name}") from error
    if not isinstance(value, dict):
        raise CurrentFixtureLoadError(f"fixture file must be an object: {path.name}")
    return value


def _string(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise CurrentFixtureLoadError(f"fixture-world.{key} must be non-empty")
    return item


def _string_list(value: dict[str, object], key: str) -> list[str]:
    items = value.get(key)
    if (
        not isinstance(items, list)
        or not items
        or not all(isinstance(item, str) and item.strip() for item in items)
    ):
        raise CurrentFixtureLoadError(f"fixture-world.{key} must be a non-empty string array")
    return items


def _reject_evaluator_fields(value: object, forbidden: set[str]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in forbidden:
                raise CurrentFixtureLoadError(f"evaluator-only fixture field: {key}")
            _reject_evaluator_fields(nested, forbidden)
    elif isinstance(value, list):
        for nested in value:
            _reject_evaluator_fields(nested, forbidden)


__all__ = [
    "CURRENT_FIXTURE_ROOT",
    "CurrentFixtureLoadError",
    "current_fixture_root_hash",
    "load_current_fixture",
]
