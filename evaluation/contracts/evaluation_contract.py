"""Shared closed-schema and stable-hash behavior for Evaluation artifacts."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict


class DuplicateJSONKeyError(ValueError):
    """Raised when strict Evaluation JSON contains an ambiguous object key."""


def load_strict_json(text: str) -> object:
    """Parse JSON while rejecting duplicate object keys at every nesting level."""

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise DuplicateJSONKeyError(f"duplicate JSON key: {key}")
            value[key] = item
        return value

    return json.loads(text, object_pairs_hook=reject_duplicate_keys)


class EvaluationContract(BaseModel):
    """Base for immutable, closed Evaluation-only JSON contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json", by_alias=True, exclude_none=False, round_trip=True),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def stable_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()
