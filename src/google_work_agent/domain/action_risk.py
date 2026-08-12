"""Canonical Action risk snapshot boundary."""

from __future__ import annotations

from json import JSONDecodeError, dumps, loads
from math import isfinite
from typing import cast

from google_work_agent.domain.errors import InvariantViolationError

MAX_ACTION_RISK_JSON_BYTES = 16 * 1024


def canonicalize_action_risk(risk: object) -> str:
    """Validate and deterministically serialize one server-owned risk object."""

    _validate_json_value(risk, path="risk")
    if not isinstance(risk, dict):
        raise InvariantViolationError("action risk must be a JSON object")
    serialized = dumps(
        risk,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )
    if len(serialized.encode("utf-8")) > MAX_ACTION_RISK_JSON_BYTES:
        raise InvariantViolationError("action risk exceeds the 16 KiB storage limit")
    return serialized


def normalize_action_risk(risk: object) -> dict[str, object]:
    """Return an isolated structured copy after applying the risk contract."""

    return cast(dict[str, object], loads(canonicalize_action_risk(risk)))


def parse_action_risk_json(serialized: str) -> dict[str, object]:
    """Decode persisted risk without accepting corrupt or non-object JSON."""

    if len(serialized.encode("utf-8")) > MAX_ACTION_RISK_JSON_BYTES:
        raise InvariantViolationError("persisted action risk exceeds the 16 KiB storage limit")
    try:
        value = loads(serialized)
    except JSONDecodeError as error:
        raise InvariantViolationError("persisted action risk is not valid JSON") from error
    return normalize_action_risk(value)


def _validate_json_value(value: object, *, path: str) -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if isfinite(value):
            return
        raise InvariantViolationError(f"{path} contains a non-finite number")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvariantViolationError(f"{path} contains a non-string object key")
            _validate_json_value(item, path=f"{path}.{key}")
        return
    raise InvariantViolationError(f"{path} contains a non-JSON value")
