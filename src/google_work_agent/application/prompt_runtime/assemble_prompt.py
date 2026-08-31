"""Bounded Product Prompt assembly from one registered base source."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Literal

from google_work_agent.application.prompt_runtime.contracts.failure_record import (
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
    activation_scope: Literal["PRODUCT", "EVALUATION"] = "PRODUCT",
) -> str:
    """Assemble one registered base source with a bounded current-Run projection.

    Product dispatch remains active-only.  The explicit Evaluation scope is the
    sole path that may assemble a DRAFT candidate for offline activation gates.
    Schema repair reuses the same base source through the exact three-field
    repair envelope instead of selecting a synthetic ``<prompt_id>.repair``
    source.
    """

    prompt_registry = registry or PromptRegistry()
    if activation_scope == "PRODUCT":
        selected = prompt_registry.lookup_by_id(prompt_ref.prompt_id)
    elif activation_scope == "EVALUATION":
        selected = prompt_registry.lookup_for_evaluation(prompt_ref.prompt_id)
    else:
        raise PromptAssemblyError(f"unknown Prompt activation scope: {activation_scope}")
    if selected != prompt_ref:
        raise PromptAssemblyError("PromptRef does not match the registered artifact")
    base_projection, candidate_output, bounded_failure = _resolve_assembly_input(
        input_projection,
        failure_record,
    )
    try:
        prompt_registry.input_contract.validate_projection(prompt_ref.prompt_id, base_projection)
    except PromptRuntimeInputContractError as error:
        raise PromptAssemblyError(str(error)) from error

    try:
        projection_json = json.dumps(
            base_projection,
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
    if bounded_failure is not None:
        try:
            failure = validate_failure_record_v1(bounded_failure)
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
        if candidate_output is not None:
            try:
                candidate_json = json.dumps(
                    candidate_output,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            except (TypeError, ValueError) as error:
                raise PromptAssemblyError("repair candidate must be JSON serializable") from error
            blocks.extend(("", "Candidate output to repair (JSON):", candidate_json))
    return "\n".join(blocks) + "\n"


def _resolve_assembly_input(
    input_projection: Mapping[str, object],
    failure_record: Mapping[str, object] | None,
) -> tuple[Mapping[str, object], object | None, Mapping[str, object] | None]:
    if set(input_projection) != {"base_projection", "candidate_output", "failure_record"}:
        return input_projection, None, failure_record
    if failure_record is not None:
        raise PromptAssemblyError("repair envelope and explicit failure_record cannot be combined")
    base_projection = input_projection.get("base_projection")
    bounded_failure = input_projection.get("failure_record")
    if not isinstance(base_projection, Mapping):
        raise PromptAssemblyError("repair base_projection must be an object")
    if not isinstance(bounded_failure, Mapping):
        raise PromptAssemblyError("repair failure_record must be an object")
    return base_projection, input_projection.get("candidate_output"), bounded_failure


__all__ = ["PromptAssemblyError", "assemble_prompt"]
