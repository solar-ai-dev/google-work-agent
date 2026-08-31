from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from tests.support.legacy_prompt_input_contract import (
    PromptRuntimeInputContractValidator,
)

from google_work_agent.application.prompt_runtime.contracts.failure_record import (
    build_failure_record_v1,
)
from google_work_agent.application.prompt_runtime.dispatch_guarded_prompt import (
    PromptInputGuardedProvider,
)
from google_work_agent.ports.llm import (
    ActualRuntime,
    LLMErrorCode,
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
)


class _Provider:
    provider_name = "fake"
    runtime = ActualRuntime.LOCAL_GPU

    def __init__(self) -> None:
        self.calls = 0

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        runtime_policy: RuntimePolicy,
        api_key: str | None,
    ) -> ProviderResponsePayload:
        del prompt_ref, prompt_input, output_schema, runtime_policy, api_key
        self.calls += 1
        return ProviderResponsePayload(
            content={},
            model="fake",
            provider_request_id=None,
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
        )


def _manifest(tmp_path: Path) -> Path:
    agent_dir = tmp_path / "prompts" / "agent"
    contract_dir = agent_dir / "contracts"
    contract_dir.mkdir(parents=True)
    manifest = agent_dir / "prompt-manifest-v1.0.0.json"
    manifest.write_text(
        json.dumps(
            {
                "runtime_input_contract": "prompts/agent/contracts/input.json",
            }
        ),
        encoding="utf-8",
    )
    (contract_dir / "input.json").write_text(
        json.dumps(
            {
                "forbidden_runtime_fields": ["interrupt_id"],
                "slots": {
                    "request_understanding.classify": {"allowed_root_fields": ["user_request"]}
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _prompt_ref() -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id="request_understanding.classify",
        prompt_version="1",
        content_hash="hash",
        agent_role="request_understanding",
        subgraph_name="request_understanding",
        node_name="classify",
        node_state="INITIAL",
        purpose="classify",
        input_schema_version="v1",
        output_schema_version="v1",
    )


def test_invalid_prompt_input_never_reaches_provider(tmp_path: Path) -> None:
    delegate = _Provider()
    guarded = PromptInputGuardedProvider(
        delegate=delegate,
        validator=PromptRuntimeInputContractValidator(_manifest(tmp_path)),
    )

    with pytest.raises(LLMInvocationError) as caught:
        guarded.invoke_structured(
            prompt_ref=_prompt_ref(),
            prompt_input={"user_request": "hello", "interrupt_id": "forged"},
            output_schema=OutputSchemaDefinition(schema_version="1", json_schema={}),
            runtime_policy=RuntimePolicy(),
            api_key=None,
        )

    assert caught.value.code is LLMErrorCode.RUNTIME_VERSION_MISMATCH
    assert delegate.calls == 0


def test_valid_prompt_input_dispatches_once(tmp_path: Path) -> None:
    delegate = _Provider()
    guarded = PromptInputGuardedProvider(
        delegate=delegate,
        validator=PromptRuntimeInputContractValidator(_manifest(tmp_path)),
    )

    guarded.invoke_structured(
        prompt_ref=_prompt_ref(),
        prompt_input={"user_request": "hello"},
        output_schema=OutputSchemaDefinition(schema_version="1", json_schema={}),
        runtime_policy=RuntimePolicy(),
        api_key=None,
    )

    assert delegate.calls == 1


def test_semantic_revision_validates_base_projection_without_widening_contract(
    tmp_path: Path,
) -> None:
    delegate = _Provider()
    guarded = PromptInputGuardedProvider(
        delegate=delegate,
        validator=PromptRuntimeInputContractValidator(_manifest(tmp_path)),
    )
    failure = build_failure_record_v1(
        failure_reason_code="SEMANTIC_CANDIDATE_INVALID",
        failure_origin="LLM_OUTPUT",
        detected_by="RUNTIME_DOMAIN_VALIDATOR",
        runtime_disposition="RETRYABLE",
        experiment_disposition="RUN_REVISION",
        affected_field_paths=["$.goal"],
    )

    guarded.invoke_structured(
        prompt_ref=_prompt_ref(),
        prompt_input={
            "base_projection": {"user_request": "hello"},
            "candidate_output": {"goal": ""},
            "failure_record": failure,
        },
        output_schema=OutputSchemaDefinition(schema_version="1", json_schema={}),
        runtime_policy=RuntimePolicy(),
        api_key=None,
    )

    assert delegate.calls == 1


def test_semantic_revision_rejects_unknown_base_projection_field(tmp_path: Path) -> None:
    delegate = _Provider()
    guarded = PromptInputGuardedProvider(
        delegate=delegate,
        validator=PromptRuntimeInputContractValidator(_manifest(tmp_path)),
    )
    failure = build_failure_record_v1(
        failure_reason_code="SEMANTIC_CANDIDATE_INVALID",
        failure_origin="LLM_OUTPUT",
        detected_by="RUNTIME_DOMAIN_VALIDATOR",
        runtime_disposition="RETRYABLE",
        experiment_disposition="RUN_REVISION",
        affected_field_paths=["$.goal"],
    )

    with pytest.raises(LLMInvocationError):
        guarded.invoke_structured(
            prompt_ref=_prompt_ref(),
            prompt_input={
                "base_projection": {
                    "user_request": "hello",
                    "interrupt_id": "forged",
                },
                "candidate_output": {"goal": ""},
                "failure_record": failure,
            },
            output_schema=OutputSchemaDefinition(schema_version="1", json_schema={}),
            runtime_policy=RuntimePolicy(),
            api_key=None,
        )

    assert delegate.calls == 0
