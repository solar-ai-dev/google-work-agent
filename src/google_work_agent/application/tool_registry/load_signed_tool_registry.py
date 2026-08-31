"""Load and validate the implementation mirror of the Signed Tool Registry."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import cast

from google_work_agent.application.tool_registry.contracts import SignedToolRegistryEntryV1
from google_work_agent.application.tool_registry.contracts.signed_tool_registry_entry import (
    RecoveryStrategy,
    RetryClass,
    ToolEffect,
    VerificationStrategy,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry

_IMPLEMENTATION_MANIFEST = Path(__file__).with_name("tool_registry_manifest.json")


_MANIFEST_FIELDS = frozenset({"schema_version", "contract_version", "entries", "entries_hash"})
_ENTRY_FIELDS = frozenset(
    {
        "schema_version",
        "connector_id",
        "resource_type",
        "tool_id",
        "effect",
        "required_scopes",
        "input_schema_ref",
        "output_schema_ref",
        "retry_class",
        "verification_strategy",
        "recovery_strategy",
    }
)


def load_signed_tool_registry(
    path: Path | None = None,
    *,
    expected_sha256: str | None = None,
) -> SignedToolRegistry:
    """Load one exact manifest and reject drift from the 07 implementation rows."""

    manifest_path = _IMPLEMENTATION_MANIFEST if path is None else path
    manifest_bytes = manifest_path.read_bytes()
    if expected_sha256 is not None and sha256(manifest_bytes).hexdigest() != expected_sha256:
        raise ValueError("Signed Tool Registry release hash mismatch")
    decoded = json.loads(manifest_bytes, object_pairs_hook=_unique_object)
    if not isinstance(decoded, dict):
        raise ValueError("SignedToolRegistryManifestV1 must be an object")
    payload = cast(dict[str, object], decoded)
    _require_exact_fields(payload, _MANIFEST_FIELDS, "SignedToolRegistryManifestV1")
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported SignedToolRegistryManifestV1 schema_version")
    contract_version = payload.get("contract_version")
    entries_payload = payload.get("entries")
    if not isinstance(contract_version, str) or not contract_version.strip():
        raise ValueError("contract_version is required")
    if not isinstance(entries_payload, list) or not entries_payload:
        raise ValueError("entries must be a non-empty list")
    entries = tuple(
        _entry_from_payload(_require_object(item, "SignedToolRegistryEntryV1"))
        for item in entries_payload
    )
    registry = SignedToolRegistry(
        entries,
        contract_version=contract_version,
    )
    if payload.get("entries_hash") != registry.entries_hash:
        raise ValueError("Signed Tool Registry entries_hash mismatch")
    return registry


def _entry_from_payload(payload: dict[str, object]) -> SignedToolRegistryEntryV1:
    _require_exact_fields(payload, _ENTRY_FIELDS, "SignedToolRegistryEntryV1")
    if payload.get("schema_version") != 1 or any(
        not isinstance(payload.get(field), str)
        for field in _ENTRY_FIELDS - {"schema_version", "required_scopes"}
    ):
        raise ValueError("SignedToolRegistryEntryV1 field type mismatch")
    required_scopes = payload["required_scopes"]
    if not isinstance(required_scopes, list) or not all(
        isinstance(value, str) for value in required_scopes
    ):
        raise ValueError("required_scopes must be a list of strings")
    return SignedToolRegistryEntryV1(
        schema_version=1,
        connector_id=str(payload["connector_id"]),
        resource_type=str(payload["resource_type"]),
        tool_id=str(payload["tool_id"]),
        effect=_tool_effect(payload["effect"]),
        required_scopes=tuple(cast(list[str], required_scopes)),
        input_schema_ref=str(payload["input_schema_ref"]),
        output_schema_ref=str(payload["output_schema_ref"]),
        retry_class=_retry_class(payload["retry_class"]),
        verification_strategy=_verification_strategy(payload["verification_strategy"]),
        recovery_strategy=_recovery_strategy(payload["recovery_strategy"]),
    )


def _tool_effect(value: object) -> ToolEffect:
    if value not in {"READ", "CREATE", "UPDATE", "SEND", "DELETE"}:
        raise ValueError("unsupported tool effect")
    return cast(ToolEffect, value)


def _retry_class(value: object) -> RetryClass:
    if value not in {"READ_BOUNDED", "WRITE_NO_AUTO_RETRY"}:
        raise ValueError("unsupported retry_class")
    return cast(RetryClass, value)


def _verification_strategy(value: object) -> VerificationStrategy:
    if value not in {"NONE", "GET_COMPARE", "GET_ABSENT", "SENT_LOOKUP"}:
        raise ValueError("unsupported verification_strategy")
    return cast(VerificationStrategy, value)


def _recovery_strategy(value: object) -> RecoveryStrategy:
    if value not in {"NONE", "GET_TARGET", "RESOURCE_SEARCH", "MESSAGE_SEARCH"}:
        raise ValueError("unsupported recovery_strategy")
    return cast(RecoveryStrategy, value)


def _require_exact_fields(
    payload: dict[str, object], expected: frozenset[str], contract_name: str
) -> None:
    actual = frozenset(payload)
    if actual != expected:
        raise ValueError(
            f"{contract_name} fields mismatch: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _require_object(value: object, contract_name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{contract_name} must be an object")
    return cast(dict[str, object], value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate signed tool registry field: {key}")
        result[key] = value
    return result


__all__ = ["load_signed_tool_registry"]
