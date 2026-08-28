"""Test-only reader for predecessor Prompt fixtures awaiting successor caller cut-over."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from google_work_agent.application.orchestration.failure_record import (
    FailureRecordValidationError,
    validate_failure_record_v1,
)
from google_work_agent.application.prompt_runtime.contracts.prompt_runtime_input_contract import (
    PromptRuntimeInputContractError,
)

PromptInputContractError = PromptRuntimeInputContractError


@dataclass(frozen=True, slots=True)
class PromptRuntimeInputContractValidator:
    manifest_path: Path

    def validate(self, *, prompt_id: str, prompt_input: Mapping[str, object]) -> None:
        manifest = _load_object(self.manifest_path)
        relative = manifest.get("runtime_input_contract")
        if not isinstance(relative, str):
            raise PromptInputContractError("runtime_input_contract is required")
        repo_root = self.manifest_path.resolve()
        while repo_root.name != "prompts" and repo_root != repo_root.parent:
            repo_root = repo_root.parent
        if repo_root.name != "prompts":
            raise PromptInputContractError("legacy fixture manifest path is invalid")
        contract = _load_object(repo_root.parent / relative)
        slots = contract.get("slots")
        if not isinstance(slots, dict) or not isinstance(slots.get(prompt_id), dict):
            raise PromptInputContractError("legacy fixture slot must be an object")
        slot = slots[prompt_id]
        allowed = slot.get("allowed_root_fields")
        if not isinstance(allowed, list) or any(not isinstance(item, str) for item in allowed):
            raise PromptInputContractError("allowed_root_fields must be strings")
        unknown = sorted(set(prompt_input) - set(allowed))
        if unknown:
            raise PromptInputContractError(
                f"prompt input contains undeclared root fields for {prompt_id}: {unknown}"
            )
        if "failure_record" in prompt_input:
            try:
                validate_failure_record_v1(prompt_input["failure_record"])
            except FailureRecordValidationError as error:
                raise PromptInputContractError(
                    f"prompt input failure_record is invalid for {prompt_id}: {error}"
                ) from error
        forbidden = contract.get("forbidden_runtime_fields", [])
        if not isinstance(forbidden, list) or any(not isinstance(item, str) for item in forbidden):
            raise PromptInputContractError("forbidden_runtime_fields must be strings")
        violations = _find_forbidden(prompt_input, set(forbidden))
        if violations:
            raise PromptInputContractError(
                f"prompt input contains forbidden runtime fields for {prompt_id}: "
                f"{sorted(violations)}"
            )


def _load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PromptInputContractError("legacy fixture JSON must be an object")
    return value


def _find_forbidden(value: object, forbidden: set[str], path: str = "$") -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}"
            if key in forbidden:
                found.add(child)
            found.update(_find_forbidden(item, forbidden, child))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.update(_find_forbidden(item, forbidden, f"{path}[{index}]"))
    return found


__all__ = ["PromptInputContractError", "PromptRuntimeInputContractValidator"]
