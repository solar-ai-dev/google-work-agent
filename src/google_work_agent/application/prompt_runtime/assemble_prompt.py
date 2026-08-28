"""Bounded Product Prompt assembly from one registered base source."""

from __future__ import annotations

import json
from collections.abc import Mapping

from google_work_agent.application.orchestration.failure_record import (
    FailureRecordValidationError,
    validate_failure_record_v1,
)
from google_work_agent.application.prompt_runtime.contracts.prompt_runtime_input_contract import (
    PromptRuntimeInputContractError,
)
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry
from google_work_agent.ports.llm import PromptReference


class PromptAssemblyError(ValueError):
    """Raised before LLM dispatch when bounded Prompt assembly fails."""


def assemble_prompt(
    prompt_ref: PromptReference,
    input_projection: Mapping[str, object],
    failure_record: Mapping[str, object] | None = None,
    *,
    registry: PromptRegistry | None = None,
) -> str:
    """Assemble one active base source with an allowlisted current-Run projection."""

    prompt_registry = registry or PromptRegistry()
    selected = prompt_registry.lookup_by_id(prompt_ref.prompt_id)
    if selected != prompt_ref:
        raise PromptAssemblyError("PromptRef does not match the active registered artifact")
    try:
        prompt_registry.input_contract.validate_projection(prompt_ref.prompt_id, input_projection)
    except PromptRuntimeInputContractError as error:
        raise PromptAssemblyError(str(error)) from error

    try:
        projection_json = json.dumps(
            input_projection,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise PromptAssemblyError("Product Prompt input must be JSON serializable") from error

    blocks = [
        prompt_registry.source_text(prompt_ref.prompt_id).rstrip(),
        "",
        "Allowed current-Run input projection (JSON):",
        projection_json,
    ]
    if failure_record is not None:
        try:
            failure = validate_failure_record_v1(failure_record)
        except FailureRecordValidationError as error:
            raise PromptAssemblyError(f"invalid failure instruction metadata: {error}") from error
        failure_instruction = {
            "failure_reason_code": failure["failure_reason_code"],
            "runtime_disposition": failure["runtime_disposition"],
            "affected_field_paths": failure["affected_field_paths"],
            "evidence_refs": failure["evidence_refs"],
        }
        blocks.extend(
            (
                "",
                "Bounded failure instruction (repair only the affected fields):",
                json.dumps(
                    failure_instruction,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            )
        )
    return "\n".join(blocks) + "\n"


__all__ = ["PromptAssemblyError", "assemble_prompt"]
