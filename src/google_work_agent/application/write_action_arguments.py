"""Typed argument extraction for write application services."""

from __future__ import annotations

from typing import cast

from google_work_agent.domain import PolicyViolationError


def dict_argument(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("expected a dict payload")
    return {str(key): cast(object, item) for key, item in value.items()}


def required_argument_string(arguments: dict[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value:
        raise PolicyViolationError(f"write action requires a non-empty {key}")
    return value


def coerce_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise TypeError("expected an int-compatible value")
