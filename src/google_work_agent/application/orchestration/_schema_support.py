"""Shared JSON-shape validation helpers for LangGraph agent output parsing.

Each agent module (``work_analysis``, ``solution_planning``, ``request_understanding``,
Retrieval, Planning, and Review modules previously defined an
identical copy of these helpers, differing only in which module-local
``ValueError`` subclass they raised. To preserve that per-module exception
identity (existing tests assert on the specific exception type), every
function here accepts ``error_cls`` explicitly and raises it verbatim instead
of hard-coding one exception type.
"""

from __future__ import annotations

from typing import cast

from google_work_agent.ports.llm import StructuredLLMResult


def require_mapping(value: object, path: str, *, error_cls: type[Exception]) -> dict[str, object]:
    if not isinstance(value, dict):
        raise error_cls(f"{path} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise error_cls(f"{path} keys must be strings")
        result[key] = item
    return result


def nullable_mapping(
    value: object, path: str, *, error_cls: type[Exception]
) -> dict[str, object] | None:
    if value is None:
        return None
    return require_mapping(value, path, error_cls=error_cls)


def require_allowed_keys(
    value: dict[str, object],
    path: str,
    *,
    required: set[str],
    optional: set[str],
    error_cls: type[Exception],
) -> None:
    actual = set(value)
    missing = required - actual
    extra = actual - required - optional
    if missing:
        raise error_cls(f"{path} is missing required fields: {sorted(missing)}")
    if extra:
        raise error_cls(f"{path} has unsupported fields: {sorted(extra)}")


def require_exact_keys(
    value: dict[str, object], path: str, keys: set[str], *, error_cls: type[Exception]
) -> None:
    require_allowed_keys(value, path, required=keys, optional=set(), error_cls=error_cls)


def require_int(
    value: dict[str, object], field: str, path: str, *, error_cls: type[Exception]
) -> int:
    item = value[field]
    if not isinstance(item, int) or isinstance(item, bool):
        raise error_cls(f"{path}.{field} must be integer")
    return item


def require_string(
    value: dict[str, object], field: str, path: str, *, error_cls: type[Exception]
) -> str:
    item = value[field]
    if not isinstance(item, str):
        raise error_cls(f"{path}.{field} must be string")
    return item


def require_list(value: object, path: str, *, error_cls: type[Exception]) -> list[object]:
    if not isinstance(value, list):
        raise error_cls(f"{path} must be an array")
    return value


def require_string_list(value: object, path: str, *, error_cls: type[Exception]) -> list[str]:
    items = require_list(value, path, error_cls=error_cls)
    for index, item in enumerate(items):
        if not isinstance(item, str):
            raise error_cls(f"{path}[{index}] must be string")
    return cast(list[str], items)


def require_schema_version(
    value: dict[str, object], path: str, expected: int, *, error_cls: type[Exception]
) -> None:
    schema_version = require_int(value, "schema_version", path, error_cls=error_cls)
    if schema_version != expected:
        raise error_cls(f"{path}.schema_version must be {expected}")


def optional_string_list(value: object, *, error_cls: type[Exception]) -> list[str]:
    if value is None:
        return []
    items = require_list(value, "$.clarification.list", error_cls=error_cls)
    result: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, str):
            raise error_cls(f"clarification list entry must be string: {index}")
        result.append(item)
    return result


def optional_option_list(value: object, *, error_cls: type[Exception]) -> list[dict[str, object]]:
    if value is None:
        return []
    items = require_list(value, "$.clarification.options", error_cls=error_cls)
    return [
        require_mapping(item, "$.clarification.options[]", error_cls=error_cls) for item in items
    ]


def validated_string_refs(
    value: object,
    allowed: set[str],
    path: str,
    label: str,
    *,
    error_cls: type[Exception],
) -> list[str]:
    refs = require_string_list(value, path, error_cls=error_cls)
    for item in refs:
        if item not in allowed:
            raise error_cls(f"{label} reference does not exist: {item}")
    return refs


def provider_summary(result: StructuredLLMResult) -> dict[str, object]:
    return {
        "provider": result.provider,
        "model": result.model,
        "requested_mode": result.requested_mode.value,
        "actual_runtime": result.actual_runtime.value,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "total_tokens": result.total_tokens,
        "latency_ms": result.latency_ms,
        "fallback_reason": result.fallback_reason,
        "structured_output_attempts": result.structured_output_attempts,
        "provider_request_id": result.provider_request_id,
        "safe_error_code": result.safe_error_code,
    }
