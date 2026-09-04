"""Provider-bound schema repair for the sole structured-inference router."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from google_work_agent.application.prompt_runtime.contracts.failure_record import (
    build_failure_record_v1,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    PRODUCT_RELEASE,
    PromptExecutionScope,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    LLMErrorCode,
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
    RuntimePolicy,
    StructuredLLMProvider,
)

_JSON_PATH_PREFIX = re.compile(r"^\$[\w.\[\]]*")


@dataclass(frozen=True, slots=True)
class PromptRepairSchemaRepairer:
    """Re-invoke the same provider with the exact active base PromptRef."""

    manifest_path: Path | None = None
    execution_scope: PromptExecutionScope = PRODUCT_RELEASE
    prompt_loader: Callable[..., PromptReference] | None = None

    def repair(
        self,
        *,
        provider: StructuredLLMProvider,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        failed_output: object,
        output_schema: OutputSchemaDefinition,
        runtime_policy: RuntimePolicy,
        api_key: str | None,
        attempt_no: int,
        max_attempts: int,
        failure_reason_code: str,
        validator_errors: tuple[str, ...],
    ) -> object:
        from google_work_agent.application.prompt_runtime.prompt_registry import (
            InactivePromptArtifactError,
            default_prompt_manifest_path,
            load_prompt_reference,
        )

        manifest_path = self.manifest_path or default_prompt_manifest_path()
        loader = self.prompt_loader or load_prompt_reference
        try:
            repair_prompt_ref = loader(
                prompt_ref.prompt_id,
                manifest_path,
                execution_scope=self.execution_scope,
            )
        except (LookupError, InactivePromptArtifactError) as error:
            raise LLMInvocationError(
                LLMErrorCode.OUTPUT_SCHEMA_INVALID,
                f"{prompt_ref.prompt_id} base prompt is unavailable for repair: {error}",
            ) from error
        if repair_prompt_ref != prompt_ref:
            raise LLMInvocationError(
                LLMErrorCode.OUTPUT_SCHEMA_INVALID,
                "repair PromptRef does not match the active base artifact",
            )

        payload = provider.invoke_structured(
            prompt_ref=repair_prompt_ref,
            prompt_input=_build_repair_input(
                prompt_ref=prompt_ref,
                prompt_input=prompt_input,
                failed_output=failed_output,
                attempt_no=attempt_no,
                max_attempts=max_attempts,
                failure_reason_code=failure_reason_code,
                validator_errors=validator_errors,
            ),
            output_schema=output_schema,
            runtime_policy=runtime_policy,
            api_key=api_key,
        )
        if not isinstance(payload.content, str):
            return payload.content
        try:
            return json.loads(payload.content)
        except json.JSONDecodeError as error:
            raise LLMInvocationError(
                LLMErrorCode.OUTPUT_SCHEMA_INVALID,
                "schema repair returned invalid JSON",
            ) from error


def _build_repair_input(
    *,
    prompt_ref: PromptReference,
    prompt_input: Mapping[str, object],
    failed_output: object,
    attempt_no: int,
    max_attempts: int,
    failure_reason_code: str,
    validator_errors: tuple[str, ...],
) -> dict[str, object]:
    del max_attempts
    affected_field_paths = sorted(
        {
            match.group(0)
            for message in validator_errors
            if (match := _JSON_PATH_PREFIX.match(message)) is not None and match.group(0) != "$"
        }
    )
    return {
        "base_projection": dict(prompt_input),
        "candidate_output": failed_output,
        "failure_record": build_failure_record_v1(
            failure_id=f"{prompt_ref.prompt_id}:{attempt_no}",
            failure_reason_code=failure_reason_code,
            failure_origin="LLM_OUTPUT",
            detected_by="RUNTIME_SCHEMA_VALIDATOR",
            runtime_disposition="RETRYABLE",
            experiment_disposition="RUN_REPAIR",
            affected_field_paths=affected_field_paths,
        ),
    }


__all__ = ["PromptRepairSchemaRepairer"]
