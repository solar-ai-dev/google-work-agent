from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from google_work_agent.adapters.llm.prompt_input_guard import PromptInputGuardedProvider
from google_work_agent.application.workflows.contracts import build_default_run_budget
from google_work_agent.application.workflows.provider_dispatch_budget import (
    bind_provider_dispatch_budget,
)
from google_work_agent.ports import (
    ActualRuntime,
    LLMToolCall,
    OutputSchemaDefinition,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
    ToolCallProviderResponse,
    ToolDefinition,
)


class _RecordingValidator:
    def __init__(self) -> None:
        self.inputs: list[Mapping[str, object]] = []

    def validate(self, *, prompt_id: str, prompt_input: Mapping[str, object]) -> None:
        del prompt_id
        self.inputs.append(prompt_input)


class _FakeProvider:
    provider_name = "fake"
    runtime = ActualRuntime.API_LLM

    def __init__(self, *, fail_structured: bool = False, fail_tool: bool = False) -> None:
        self.fail_structured = fail_structured
        self.fail_tool = fail_tool
        self.structured_dispatches = 0
        self.tool_dispatches = 0

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
        self.structured_dispatches += 1
        if self.fail_structured:
            raise TimeoutError("provider timeout after dispatch")
        return ProviderResponsePayload(
            content={"ok": True},
            model="fake-model",
            provider_request_id="request-1",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
        )

    def invoke_tool_call(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        tools: Sequence[ToolDefinition],
        runtime_policy: RuntimePolicy,
        api_key: str | None,
    ) -> ToolCallProviderResponse:
        del prompt_ref, prompt_input, tools, runtime_policy, api_key
        self.tool_dispatches += 1
        if self.fail_tool:
            raise TimeoutError("tool provider timeout after dispatch")
        return ToolCallProviderResponse(
            calls=(LLMToolCall(name="fake_tool", arguments={}),),
            model="fake-model",
            provider_request_id="request-tool-1",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
        )


def _prompt_ref(prompt_id: str = "test.slot") -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id=prompt_id,
        prompt_version="1",
        content_hash="0" * 64,
        agent_role="test",
        subgraph_name="test",
        node_name="test",
        node_state="INITIAL",
        purpose="test",
        input_schema_version="1",
        output_schema_version="1",
    )


def _schema() -> OutputSchemaDefinition:
    return OutputSchemaDefinition(schema_version="1", json_schema={"type": "object"})


def _invoke_structured(guarded: PromptInputGuardedProvider, *, prompt_input=None) -> None:
    guarded.invoke_structured(
        prompt_ref=_prompt_ref(),
        prompt_input={} if prompt_input is None else prompt_input,
        output_schema=_schema(),
        runtime_policy=RuntimePolicy(),
        api_key=None,
    )


def test_failed_primary_dispatch_is_counted_before_timeout() -> None:
    budget = build_default_run_budget()
    bind_provider_dispatch_budget(budget)
    provider = _FakeProvider(fail_structured=True)
    guarded = PromptInputGuardedProvider(provider, _RecordingValidator())

    with pytest.raises(TimeoutError, match="provider timeout"):
        _invoke_structured(guarded)

    assert provider.structured_dispatches == 1
    assert budget["llm_calls_used"] == 1


def test_failed_primary_plus_successful_fallback_counts_two_dispatches() -> None:
    budget = build_default_run_budget()
    bind_provider_dispatch_budget(budget)
    primary = _FakeProvider(fail_structured=True)
    fallback = _FakeProvider()
    primary_guard = PromptInputGuardedProvider(primary, _RecordingValidator())
    fallback_guard = PromptInputGuardedProvider(fallback, _RecordingValidator())

    with pytest.raises(TimeoutError):
        _invoke_structured(primary_guard)
    _invoke_structured(fallback_guard)

    assert primary.structured_dispatches == 1
    assert fallback.structured_dispatches == 1
    assert budget["llm_calls_used"] == 2


def test_failed_schema_repair_dispatch_counts_and_uses_canonical_failure_record() -> None:
    budget = build_default_run_budget()
    bind_provider_dispatch_budget(budget)
    initial = _FakeProvider()
    repair = _FakeProvider(fail_structured=True)
    initial_guard = PromptInputGuardedProvider(initial, _RecordingValidator())
    validator = _RecordingValidator()
    repair_guard = PromptInputGuardedProvider(repair, validator)

    _invoke_structured(initial_guard)
    legacy_repair_input = {
        "base_projection": {"request_intent": {}},
        "candidate_output": {"bad": True},
        "failure_record": {
            "schema_version": 1,
            "failure_id": "repair-1",
            "failure_reason_code": "OUTPUT_SCHEMA_INVALID",
            "failure_origin": "RUNTIME",
            "detected_by": "STRUCTURED_OUTPUT_VALIDATOR",
            "runtime_disposition": "RETRYABLE",
            "experiment_disposition": "RUN_REPAIR",
            "affected_field_paths": ["$.bad"],
            "evidence_refs": [],
        },
    }
    with pytest.raises(TimeoutError, match="provider timeout"):
        _invoke_structured(repair_guard, prompt_input=legacy_repair_input)

    assert initial.structured_dispatches == 1
    assert repair.structured_dispatches == 1
    assert budget["llm_calls_used"] == 2
    normalized = validator.inputs[-1]["failure_record"]
    assert isinstance(normalized, Mapping)
    assert normalized["failure_origin"] == "LLM_OUTPUT"
    assert normalized["detected_by"] == "RUNTIME_SCHEMA_VALIDATOR"
    assert set(normalized) == {
        "schema_version",
        "failure_id",
        "failure_reason_code",
        "failure_origin",
        "detected_by",
        "runtime_disposition",
        "experiment_disposition",
        "affected_field_paths",
        "evidence_refs",
    }


def test_failed_tool_call_dispatch_is_counted() -> None:
    budget = build_default_run_budget()
    bind_provider_dispatch_budget(budget)
    provider = _FakeProvider(fail_tool=True)
    guarded = PromptInputGuardedProvider(provider, _RecordingValidator())

    with pytest.raises(TimeoutError, match="tool provider timeout"):
        guarded.invoke_tool_call(
            prompt_ref=_prompt_ref(),
            prompt_input={},
            tools=(ToolDefinition(name="fake_tool", description="fake", parameters={}),),
            runtime_policy=RuntimePolicy(),
            api_key=None,
        )

    assert provider.tool_dispatches == 1
    assert budget["llm_calls_used"] == 1
