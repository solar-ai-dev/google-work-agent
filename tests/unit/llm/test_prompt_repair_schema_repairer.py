"""Unit tests for base-slot + bounded-failure Schema Repair."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from tests.support.canonical_prompt_runtime import (
    activate_prompt_slot,
    copy_prompt_runtime_artifacts,
    deactivate_prompt_slot,
)
from tests.support.fakes import FakeAPIProviderTransport

from google_work_agent.adapters.llm.gemini.structured_inference import (
    GeminiStructuredInferenceAdapter,
)
from google_work_agent.adapters.llm.runtime.prompt_repair_schema_repairer import (
    PromptRepairSchemaRepairer,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import (
    PromptRegistry,
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    LLMErrorCode,
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
)

OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="1",
    json_schema={
        "type": "object",
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
        "additionalProperties": False,
    },
)


def _active_manifest(tmp_path: Path) -> Path:
    manifest_path, _ = copy_prompt_runtime_artifacts(tmp_path)
    activate_prompt_slot(manifest_path, "planning.compose_answer")
    return manifest_path


def _provider(transport: FakeAPIProviderTransport) -> GeminiStructuredInferenceAdapter:
    return GeminiStructuredInferenceAdapter(
        provider_name="generic-api", transport=transport, model="m"
    )


def test_repair_dispatches_the__same_base_prompt__with_full_input_shape(
    tmp_path: Path,
) -> None:
    manifest_path = _active_manifest(tmp_path)
    transport = FakeAPIProviderTransport()
    transport.queued_payloads.append(
        ProviderResponsePayload(
            content={"answer": "fixed"},
            model="m",
            provider_request_id=None,
            input_tokens=None,
            output_tokens=None,
            latency_ms=0,
        )
    )
    repairer = PromptRepairSchemaRepairer(manifest_path=manifest_path)
    active_prompt_ref = load_prompt_reference("planning.compose_answer", manifest_path)
    base_projection: dict[str, object] = {
        "user_request": "summarize",
        "request_intent": {"goal": "summary"},
        "answer_outline": {"sections": ["summary"]},
        "evidence": [],
    }

    result = repairer.repair(
        provider=_provider(transport),
        prompt_ref=active_prompt_ref,
        prompt_input=base_projection,
        failed_output={"answer": 123},
        output_schema=OUTPUT_SCHEMA,
        runtime_policy=RuntimePolicy(),
        api_key="key-1",
        attempt_no=1,
        max_attempts=1,
        failure_reason_code=LLMErrorCode.OUTPUT_SCHEMA_INVALID.value,
        validator_errors=("$.answer must be string",),
    )

    assert result == {"answer": "fixed"}
    assert len(transport.invocations) == 1
    call = transport.invocations[0]
    assert call["prompt_id"] == "planning.compose_answer"
    repair_input = cast(dict[str, object], call["prompt_input"])
    # 15 section 9.2 / prompt-runtime-input-contract-v1.json: exactly
    # base_projection + candidate_output + failure_record at root -- no
    # legacy original_input/previous_output/validator_errors/
    # changed_fields_allowed/attempt_no/schema_version root fields.
    assert set(repair_input) == {"base_projection", "candidate_output", "failure_record"}
    assert repair_input["base_projection"] == base_projection
    assert repair_input["candidate_output"] == {"answer": 123}
    failure_record = cast(dict[str, object], repair_input["failure_record"])
    assert failure_record["failure_reason_code"] == "OUTPUT_SCHEMA_INVALID"
    assert failure_record["failure_origin"] == "LLM_OUTPUT"
    assert failure_record["detected_by"] == "RUNTIME_SCHEMA_VALIDATOR"
    assert failure_record["affected_field_paths"] == ["$.answer"]
    assert failure_record["failure_id"] == "planning.compose_answer:1"
    assembled = assemble_prompt(
        active_prompt_ref,
        repair_input,
        registry=PromptRegistry(manifest_path),
    )
    assert "Bounded failure instruction" in assembled
    assert '"failure_reason_code":"OUTPUT_SCHEMA_INVALID"' in assembled


def test_repair_resolves__the_exact__base_prompt_id(tmp_path: Path) -> None:
    manifest_path = _active_manifest(tmp_path)
    transport = FakeAPIProviderTransport()
    transport.queued_payloads.append(
        ProviderResponsePayload(
            content={"answer": "fixed"},
            model="m",
            provider_request_id=None,
            input_tokens=None,
            output_tokens=None,
            latency_ms=0,
        )
    )
    repairer = PromptRepairSchemaRepairer(manifest_path=manifest_path)
    active_prompt_ref = load_prompt_reference("planning.compose_answer", manifest_path)

    repairer.repair(
        provider=_provider(transport),
        prompt_ref=active_prompt_ref,
        prompt_input={},
        failed_output={"answer": 1},
        output_schema=OUTPUT_SCHEMA,
        runtime_policy=RuntimePolicy(),
        api_key="key-1",
        attempt_no=1,
        max_attempts=1,
        failure_reason_code=LLMErrorCode.OUTPUT_SCHEMA_INVALID.value,
        validator_errors=("$.answer must be string",),
    )

    assert transport.invocations[0]["prompt_id"] == "planning.compose_answer"


def test_repair_fails_closed__when_sibling_prompt__is_still_draft(tmp_path: Path) -> None:
    """The DRAFT base source must remain unavailable to Product repair."""
    manifest_path, contract_path = copy_prompt_runtime_artifacts(tmp_path)
    deactivate_prompt_slot(manifest_path, "planning.compose_answer")
    transport = FakeAPIProviderTransport()
    repairer = PromptRepairSchemaRepairer(manifest_path=manifest_path)
    draft_prompt_ref = PromptRegistry(
        manifest_path, contract_path
    ).lookup_for_evaluation("planning.compose_answer")

    with pytest.raises(LLMInvocationError) as excinfo:
        repairer.repair(
            provider=_provider(transport),
            prompt_ref=draft_prompt_ref,
            prompt_input={},
            failed_output={"answer": 1},
            output_schema=OUTPUT_SCHEMA,
            runtime_policy=RuntimePolicy(),
            api_key="key-1",
            attempt_no=1,
            max_attempts=1,
            failure_reason_code=LLMErrorCode.OUTPUT_SCHEMA_INVALID.value,
            validator_errors=("$.answer must be string",),
        )
    assert excinfo.value.code is LLMErrorCode.OUTPUT_SCHEMA_INVALID
    assert transport.invocations == []


def test_repair_fails_closed__when_base_slot__does_not_exist(tmp_path: Path) -> None:
    manifest_path = default_prompt_manifest_path()
    transport = FakeAPIProviderTransport()
    repairer = PromptRepairSchemaRepairer(manifest_path=manifest_path)
    no_sibling_ref = PromptReference(
        prompt_bundle_version="agent-r4-v0.1-baseline",
        prompt_id="does_not_exist.classify",
        prompt_version="v0.1",
        content_hash="hash",
        agent_role="x",
        subgraph_name="x",
        node_name="classify",
        node_state="BASELINE",
        purpose="classify",
        input_schema_version="agent-node-input-v0.1",
        output_schema_version="agent-node-output-v0.1",
    )

    with pytest.raises(LLMInvocationError) as excinfo:
        repairer.repair(
            provider=_provider(transport),
            prompt_ref=no_sibling_ref,
            prompt_input={},
            failed_output={"answer": 1},
            output_schema=OUTPUT_SCHEMA,
            runtime_policy=RuntimePolicy(),
            api_key="key-1",
            attempt_no=1,
            max_attempts=1,
            failure_reason_code=LLMErrorCode.OUTPUT_SCHEMA_INVALID.value,
            validator_errors=("$.answer must be string",),
        )
    assert excinfo.value.code is LLMErrorCode.OUTPUT_SCHEMA_INVALID
    assert transport.invocations == []
