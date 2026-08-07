"""Canonical JSON normalization and hashing helpers."""

from __future__ import annotations

from hashlib import sha256
from json import dumps

type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


def canonicalize_json_value(value: object) -> str:
    """Serialize a JSON value into a deterministic canonical JSON string."""

    return dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def calculate_canonical_json_hash(value: object) -> str:
    """Calculate the SHA-256 hash from the canonical JSON bytes."""

    canonical_json = canonicalize_json_value(value)
    return sha256(canonical_json.encode("utf-8")).hexdigest()
