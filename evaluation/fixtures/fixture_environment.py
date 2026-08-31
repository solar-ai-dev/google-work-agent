"""Per-item clean fixture environment and durable-effect replay."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, cast

from evaluation.contracts.current_fixture_snapshot import CurrentFixtureSnapshotV1


class FixtureEffectError(ValueError):
    """Raised when an observed durable effect cannot be replayed deterministically."""


class FixtureEnvironment:
    def __init__(self, snapshot: CurrentFixtureSnapshotV1) -> None:
        self._snapshot = snapshot
        self._state = cast(dict[str, object], json.loads(snapshot.canonical_json()))

    @property
    def initial_hash(self) -> str:
        return self._snapshot.stable_hash()

    def snapshot(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(json.dumps(self._state, ensure_ascii=False)))

    def replay(self, effects: Sequence[Mapping[str, object]]) -> dict[str, object]:
        for effect in effects:
            operation = effect.get("operation")
            collection = effect.get("collection")
            resource_id = effect.get("resource_id")
            if operation not in {"CREATE", "UPDATE", "DELETE"}:
                raise FixtureEffectError("durable effect operation is invalid")
            if not isinstance(collection, str) or not isinstance(resource_id, str):
                raise FixtureEffectError("durable effect identity is invalid")
            rows = self._collection(collection)
            index = next((i for i, row in enumerate(rows) if resource_id in row.values()), None)
            if operation == "CREATE":
                value = effect.get("after")
                if index is not None or not isinstance(value, Mapping):
                    raise FixtureEffectError("CREATE must add one absent object")
                rows.append(dict(value))
            elif operation == "UPDATE":
                value = effect.get("after")
                if index is None or not isinstance(value, Mapping):
                    raise FixtureEffectError("UPDATE must replace one existing object")
                rows[index] = dict(value)
            else:
                if index is None:
                    raise FixtureEffectError("DELETE must remove one existing object")
                rows.pop(index)
        return self.snapshot()

    def _collection(self, dotted: str) -> list[dict[str, Any]]:
        value: object = self._state
        for part in dotted.split("."):
            if not isinstance(value, dict) or part not in value:
                raise FixtureEffectError(f"unknown fixture collection: {dotted}")
            value = value[part]
        if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
            raise FixtureEffectError(f"fixture collection is not an object array: {dotted}")
        return value


__all__ = ["FixtureEffectError", "FixtureEnvironment"]
