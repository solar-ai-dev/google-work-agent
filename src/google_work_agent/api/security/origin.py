"""Origin validation helpers."""

from __future__ import annotations


def is_exact_origin_match(origin: str | None, *, expected_origin: str) -> bool:
    if origin is None:
        return False
    return origin.strip().lower() == expected_origin.lower()
