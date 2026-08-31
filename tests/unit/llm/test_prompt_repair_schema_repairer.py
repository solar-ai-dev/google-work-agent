"""Unit tests for base-slot + bounded-failure Schema Repair."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from tests.support.fakes import FakeAPIProviderTransport
from tests.support.prompt_manifests import (
    canonical_prompt_manifest_path,
    write_runtime_active_manifest,
)

from google_work_agent.adapters.llm.gemini.structured_inference import (
    GeminiStructuredInferenceAdapter,
)
from google_work_agent.adapters.llm.runtime.prompt_repair_schema_repairer import (
    PromptRepairSchemaRepairer,
)
from google_work_agent.application.prompt_runtime.prompt_registry import load_prompt_reference
from google_work_agent.ports.llm import (
    LLMErrorCode,
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
)

ANALYZE_PROMPT_REF = PromptReference(
    prompt_bundle_version="agent-r4-v0.1-baseline",
    prompt_id="work_analysis.analyze",
    prompt_version="v0.1",
    content_hash="hash",
    agent_role="work_analysis",
    subgraph_name="work_analysis",
    node_name="analyze",
    node_state="BASELINE",
    purpose="analyze",
    input_schema_version="agent-node-input-v0.1",
    output_schema_version="agent-node-output-v0.1",
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


def _provider(transport: FakeAPIProviderTransport) -> GeminiStructuredInferenceAdapter:
    return GeminiStructuredInferenceAdapter(
        provider_name="generic-api", transport=transport, model="m"
    )


def test_repair_dispatches_the_same_base_prompt_with_full_input_shape(
    tmp_path: Path,
) -> None:
    manifest_path = write_runtime_active_manifest(
        tmp_path, prompt_ids=["work_analysis.analyze"]
    )
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
    active_prompt_ref = load_prompt_reference("work_analysis.analyze", manifest_path)

    result = repairer.repair(
        provider=_provider(transport),
        prompt_ref=active_prompt_ref,
        prompt_input={"topic": "hello"},
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
    assert call["prompt_id"] == "work_analysis.analyze"
    repair_input = cast(dict[str, object], call["prompt_input"])
    # 15 section 9.2 / prompt-runtime-input-contract-v1.json: exactly
    # base_projection + candidate_output + failure_record at root -- no
    # legacy original_input/previous_output/validator_errors/
    # changed_fields_allowed/attempt_no/schema_version root fields.
    assert set(repair_input) == {"base_projection", "candidate_output", "failure_record"}
    assert repair_input["base_projection"] == {"topic": "hello"}
    assert repair_input["candidate_output"] == {"answer": 123}
    failure_record = cast(dict[str, object], repair_input["failure_record"])
    assert failure_record["failure_reason_code"] == "OUTPUT_SCHEMA_INVALID"
    assert failure_record["affected_field_paths"] == ["$.answer"]
    assert failure_record["failure_id"] == "work_analysis.analyze:1"


def test_repair_resolves_the_exact_base_prompt_id(tmp_path: Path) -> None:
    manifest_path = write_runtime_active_manifest(
        tmp_path, prompt_ids=["work_analysis.analyze"]
    )
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
    active_prompt_ref = load_prompt_reference("work_analysis.analyze", manifest_path)

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

    assert transport.invocations[0]["prompt_id"] == "work_analysis.analyze"


def test_repair_fails_closed_when_sibling_prompt_is_still_draft() -> None:
    """The DRAFT base source must remain unavailable to Product repair."""
    transport = FakeAPIProviderTransport()
    repairer = PromptRepairSchemaRepairer(manifest_path=canonical_prompt_manifest_path())

    with pytest.raises(LLMInvocationError) as excinfo:
        repairer.repair(
            provider=_provider(transport),
            prompt_ref=ANALYZE_PROMPT_REF,
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


def test_repair_fails_closed_when_base_slot_does_not_exist(tmp_path: Path) -> None:
    manifest_path = canonical_prompt_manifest_path()
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
