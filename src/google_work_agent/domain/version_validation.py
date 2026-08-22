"""Shared non-negative aggregate-version invariant."""


def is_non_negative_version(value: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
