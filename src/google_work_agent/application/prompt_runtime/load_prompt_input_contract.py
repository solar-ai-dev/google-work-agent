"""Sole loader for the canonical Product Prompt input-contract artifact."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from google_work_agent.application.prompt_runtime.contracts.prompt_runtime_input_contract import (
    REQUIRED_PROMPT_RUNTIME_NODE_BY_SLOT,
    REQUIRED_PROMPT_SLOT_IDS,
    PromptRuntimeInputContractEntryV1,
    PromptRuntimeInputContractError,
    PromptRuntimeInputContractV1,
)

_PACKAGE_DIR = Path(__file__).resolve().parent
_DEFAULT_CONTRACT_PATH = _PACKAGE_DIR / "prompt_runtime_input_contract_v1.json"
_ROOT_FIELDS = {"schema_version", "forbidden_input_fields", "entries"}
_ENTRY_FIELDS = {
    "prompt_slot_id",
    "runtime_node_id",
    "input_schema_version",
    "required_root_fields",
    "optional_root_fields",
    "output_schema_version",
}


def default_prompt_input_contract_path() -> Path:
    return _DEFAULT_CONTRACT_PATH


def load_prompt_input_contract(
    path: Path | None = None,
    *,
    manifest_slot_ids: frozenset[str] | None = None,
    source_slot_ids: frozenset[str] | None = None,
) -> PromptRuntimeInputContractV1:
    """Load and fail-close the exact Canonical 21-slot input contract."""

    contract = _load_prompt_input_contract((path or _DEFAULT_CONTRACT_PATH).resolve())
    expected = REQUIRED_PROMPT_SLOT_IDS
    if contract.slot_ids != expected:
        _raise_set_mismatch("input-contract", expected, contract.slot_ids)
    for entry in contract.entries:
        expected_node = REQUIRED_PROMPT_RUNTIME_NODE_BY_SLOT[entry.prompt_slot_id]
        if entry.runtime_node_id != expected_node:
            raise PromptRuntimeInputContractError(
                f"runtime_node_id mismatch for {entry.prompt_slot_id}: "
                f"{entry.runtime_node_id!r} != {expected_node!r}"
            )
        forbidden_allowlist = {
            field.replace("-", "_").lower() for field in entry.allowed_root_fields
        } & contract.forbidden_input_fields
        if forbidden_allowlist:
            raise PromptRuntimeInputContractError(
                f"forbidden fields appear in allowlist for {entry.prompt_slot_id}: "
                f"{sorted(forbidden_allowlist)}"
            )
    if manifest_slot_ids is not None and manifest_slot_ids != expected:
        _raise_set_mismatch("manifest", expected, manifest_slot_ids)
    if source_slot_ids is not None and source_slot_ids != expected:
        _raise_set_mismatch("sources", expected, source_slot_ids)
    return contract


def _load_prompt_input_contract(path: Path) -> PromptRuntimeInputContractV1:
    try:
        raw = path.read_text(encoding="utf-8", errors="strict")
        payload = json.loads(raw, object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PromptRuntimeInputContractError("prompt input-contract is unreadable") from error
    root = _require_object(payload, "$")
    _require_exact_fields(root, _ROOT_FIELDS, "$")
    schema_version = _require_int(root.get("schema_version"), "$.schema_version")
    forbidden = frozenset(
        item.lower().replace("-", "_")
        for item in _require_string_list(
            root.get("forbidden_input_fields"), "$.forbidden_input_fields"
        )
    )
    raw_entries = root.get("entries")
    if not isinstance(raw_entries, list):
        raise PromptRuntimeInputContractError("$.entries must be an array")
    entries: list[PromptRuntimeInputContractEntryV1] = []
    for index, raw_entry in enumerate(raw_entries):
        entry_path = f"$.entries[{index}]"
        item = _require_object(raw_entry, entry_path)
        _require_exact_fields(item, _ENTRY_FIELDS, entry_path)
        entries.append(
            PromptRuntimeInputContractEntryV1(
                prompt_slot_id=_require_string(item.get("prompt_slot_id"), entry_path),
                runtime_node_id=_require_string(item.get("runtime_node_id"), entry_path),
                input_schema_version=_require_int(
                    item.get("input_schema_version"), f"{entry_path}.input_schema_version"
                ),
                required_root_fields=tuple(
                    _require_string_list(
                        item.get("required_root_fields"),
                        f"{entry_path}.required_root_fields",
                    )
                ),
                optional_root_fields=tuple(
                    _require_string_list(
                        item.get("optional_root_fields"),
                        f"{entry_path}.optional_root_fields",
                    )
                ),
                output_schema_version=_require_int(
                    item.get("output_schema_version"), f"{entry_path}.output_schema_version"
                ),
            )
        )
    return PromptRuntimeInputContractV1(
        schema_version=schema_version,
        entries=tuple(entries),
        forbidden_input_fields=forbidden,
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PromptRuntimeInputContractError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _require_object(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PromptRuntimeInputContractError(f"{path} must be an object")
    return cast(dict[str, object], value)


def _require_exact_fields(value: dict[str, object], expected: set[str], path: str) -> None:
    actual = set(value)
    if actual != expected:
        raise PromptRuntimeInputContractError(
            f"{path} fields mismatch; missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)}"
        )


def _require_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PromptRuntimeInputContractError(f"{path} must be a non-empty string")
    return value


def _require_int(value: object, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise PromptRuntimeInputContractError(f"{path} must be an integer")
    return value


def _require_string_list(value: object, path: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise PromptRuntimeInputContractError(f"{path} must be a non-empty-string array")
    strings = cast(list[str], value)
    if len(strings) != len(set(strings)):
        raise PromptRuntimeInputContractError(f"{path} contains duplicates")
    return strings


def _raise_set_mismatch(label: str, expected: frozenset[str], actual: frozenset[str]) -> None:
    raise PromptRuntimeInputContractError(
        f"{label} slot set mismatch; missing={sorted(expected - actual)}, "
        f"extra={sorted(actual - expected)}"
    )


__all__ = ["default_prompt_input_contract_path", "load_prompt_input_contract"]
