"""Deterministic Product Prompt runtime-input contract enforcement.

The prompt manifest names the versioned runtime-input contract, while that
contract owns the per-slot root allowlist and globally forbidden runtime
fields. This module is deliberately provider-agnostic: it validates only the
typed projection that is about to be serialized into a Product Prompt.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from google_work_agent.application.workflows.failure_record import (
    FailureRecordValidationError,
    validate_failure_record_v1,
)


class PromptInputContractError(ValueError):
    """Raised before provider dispatch when a Product Prompt input is invalid."""


@dataclass(frozen=True, slots=True)
class PromptRuntimeInputContractValidator:
    """Validate one Product Prompt input against the manifest-owned contract."""

    manifest_path: Path

    def validate(self, *, prompt_id: str, prompt_input: Mapping[str, object]) -> None:
        contract = _load_contract_for_manifest(self.manifest_path)
        slots = _require_mapping(contract.get("slots"), "$.slots")
        slot = _require_mapping(slots.get(prompt_id), f"$.slots.{prompt_id}")
        allowed = _require_string_set(
            slot.get("allowed_root_fields"), f"$.slots.{prompt_id}.allowed_root_fields"
        )
        actual = set(prompt_input)
        undeclared = sorted(actual - allowed)
        if undeclared:
            raise PromptInputContractError(
                f"prompt input contains undeclared root fields for {prompt_id}: {undeclared}"
            )

        # Repair/revision roots remain base_projection + candidate_output +
        # failure_record, while the nested failure_record is itself a closed,
        # versioned DTO.  Reject bespoke legacy fields before serialization.
        if "failure_record" in prompt_input:
            try:
                validate_failure_record_v1(prompt_input["failure_record"])
            except FailureRecordValidationError as error:
                raise PromptInputContractError(
                    f"prompt input failure_record is invalid for {prompt_id}: {error}"
                ) from error

        forbidden = _require_string_set(
            contract.get("forbidden_runtime_fields"), "$.forbidden_runtime_fields"
        )
        violations = sorted(_find_forbidden_fields(prompt_input, forbidden))
        if violations:
            raise PromptInputContractError(
                f"prompt input contains forbidden runtime fields for {prompt_id}: {violations}"
            )


@lru_cache(maxsize=8)
def _load_contract_for_manifest(manifest_path: Path) -> dict[str, object]:
    manifest = _load_json_object(manifest_path, "prompt manifest")
    relative_contract_path = manifest.get("runtime_input_contract")
    if not isinstance(relative_contract_path, str) or not relative_contract_path.strip():
        raise PromptInputContractError("prompt manifest runtime_input_contract is required")

    repo_root = _repo_root_for_manifest(manifest_path)
    contract_path = (repo_root / relative_contract_path).resolve()
    try:
        contract_path.relative_to(repo_root)
    except ValueError as error:
        raise PromptInputContractError("runtime input contract escapes repository root") from error
    if not contract_path.is_file():
        raise PromptInputContractError(
            f"prompt runtime input contract is missing: {relative_contract_path}"
        )
    return _load_json_object(contract_path, "prompt runtime input contract")


def _repo_root_for_manifest(manifest_path: Path) -> Path:
    resolved = manifest_path.resolve()
    # Canonical location: <repo>/prompts/agent/prompt-manifest-vX.Y.Z.json.
    # Resolve structurally rather than depending on the process working directory.
    if resolved.parent.name != "agent" or resolved.parent.parent.name != "prompts":
        raise PromptInputContractError(
            "prompt manifest is outside the canonical prompts/agent path"
        )
    return resolved.parent.parent.parent


def _load_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PromptInputContractError(f"{label} is unreadable") from error
    return _require_mapping(value, f"${label}")


def _require_mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PromptInputContractError(f"{path} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise PromptInputContractError(f"{path} keys must be strings")
        result[key] = item
    return result


def _require_string_set(value: object, path: str) -> frozenset[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise PromptInputContractError(f"{path} must be a string array")
    return frozenset(value)


def _find_forbidden_fields(value: object, forbidden: frozenset[str], path: str = "$") -> set[str]:
    violations: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            item_path = f"{path}.{key_text}"
            if key_text in forbidden:
                violations.add(item_path)
            violations.update(_find_forbidden_fields(item, forbidden, item_path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            violations.update(_find_forbidden_fields(item, forbidden, f"{path}[{index}]"))
    return violations


__all__ = ["PromptInputContractError", "PromptRuntimeInputContractValidator"]
