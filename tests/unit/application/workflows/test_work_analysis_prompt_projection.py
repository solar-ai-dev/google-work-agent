"""Prove the normal-Retrieval Work Analysis caller satisfies the real
Prompt Runtime Input Contract (``work_analysis.analyze``), not a synthetic
fixture contract -- this is the P0 blocker closed by aligning
``WorkAnalysisAgent.invoke_analyze_llm_from_retrieval_result`` with the
same bounded projection ``canonical_optional_inputs.py`` already uses for
the no-Retrieval optional path.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, cast

import pytest

from google_work_agent.adapters.llm.prompt_input_guard import PromptInputGuardedProvider
from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows import (
    EvidenceDraftV1,
    RequestIntentV2,
    RetrievalResultV1,
    WorkAnalysisAgent,
)
from google_work_agent.application.workflows.prompt_input_contract import (
    PromptRuntimeInputContractValidator,
)
from google_work_agent.application.workflows.prompt_registry import (
    default_prompt_manifest_path,
)
from google_work_agent.ports import (
    ActualRuntime,
    LLMErrorCode,
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
    ProviderResponsePayload,
    RequestedRuntimeMode,
    RuntimePolicy,
    StructuredLLMResult,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)

_WORK_ANALYSIS_ANALYZE_PROMPT_REF = PromptReference(
    prompt_bundle_version="agent-r8.6",
    prompt_id="work_analysis.analyze",
    prompt_version="0.9.0",
    content_hash="hash",
    agent_role="work_analysis",
    subgraph_name="work_analysis",
    node_name="analyze",
    node_state="INITIAL",
    purpose="analyze",
    input_schema_version="r8.6-runtime-input-snapshot-v1",
    output_schema_version="r8.6-output-contract-snapshot-v1",
)


@dataclass
class _FakeStructuredLLMRuntime:
    """Captures the exact ``prompt_input`` a production caller builds."""

    queued: deque[StructuredLLMResult] = field(default_factory=deque)
    calls: list[dict[str, object]] = field(default_factory=list)

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
        semantic_validate: Callable[[object], object] | None = None,
    ) -> StructuredLLMResult:
        self.calls.append({"prompt_ref": prompt_ref, "prompt_input": dict(prompt_input)})
        return self.queued.popleft()


class _FakeRawProvider:
    """Fake provider directly beneath ``PromptInputGuardedProvider``."""

    provider_name = "fake"
    runtime = ActualRuntime.LOCAL_GPU

    def __init__(self) -> None:
        self.calls = 0

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: dict[str, object],
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


def _agent(runtime: _FakeStructuredLLMRuntime) -> WorkAnalysisAgent:
    return WorkAnalysisAgent(
        llm_runtime=runtime,  # type: ignore[arg-type]
        analyze_prompt_ref=_WORK_ANALYSIS_ANALYZE_PROMPT_REF,
    )


def _request() -> WorkflowStartRequest:
    return WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="Analyze risky follow-up work.",
        selected_resource_ids=(),
        correlation=WorkflowCorrelationContext(
            request_id="request-1",
            command_id="command-1",
            api_contract_version="v1",
        ),
    )


def _intent() -> RequestIntentV2:
    return {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "Find follow-up risks",
        "completion_conditions": ["Evidence-backed work analysis is available."],
    }


def _retrieval_result() -> RetrievalResultV1:
    return {
        "schema_version": 1,
        "meta": {"artifact_id": "retrieval-1", "revision": 1, "based_on": []},
        "coverage": cast(Literal["SUFFICIENT", "PARTIAL", "NO_FETCH_NEEDED"], "SUFFICIENT"),
        "context_bundle_ref": None,
        "evidence_refs": ["evidence-1"],
        "selected_segment_ids": ["seg-1"],
        "source_resource_refs": ["gmail_thread:thread-kim"],
        "source_statuses": [],
        "missing_information": [],
        "retrieval_rounds": 1,
    }


def _evidence_drafts() -> list[EvidenceDraftV1]:
    return [
        {
            "schema_version": 1,
            "evidence_id": "evidence-1",
            "resource_handle": "gmail_thread:thread-kim",
            "segment_id": "seg-1",
            "kind": "excerpt",
            "excerpt": "Kim is waiting for the follow-up task.",
            "locator": {"kind": "resource_payload"},
            "reason_codes": ["GOAL_RELEVANT"],
        }
    ]


def _real_validator() -> PromptRuntimeInputContractValidator:
    return PromptRuntimeInputContractValidator(manifest_path=default_prompt_manifest_path())


def _dummy_output_schema() -> OutputSchemaDefinition:
    return OutputSchemaDefinition(schema_version="1", json_schema={})


def _llm_result(payload: object) -> StructuredLLMResult:
    return StructuredLLMResult(
        structured_output=payload,
        provider="fake",
        model="fake-model",
        requested_mode=RequestedRuntimeMode.AUTO,
        actual_runtime=ActualRuntime.API_LLM,
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        latency_ms=5,
        estimated_cost_usd=None,
        fallback_reason=None,
        structured_output_attempts=1,
        provider_request_id="provider-request-1",
        safe_error_code=None,
    )


def test_normal_retrieval_path_prompt_input_satisfies_real_contract() -> None:
    """A: capture the actual caller's prompt_input and validate it against
    the real production contract -- must PASS."""
    runtime = _FakeStructuredLLMRuntime()
    runtime.queued.append(_llm_result({}))
    agent = _agent(runtime)

    agent.invoke_analyze_llm_from_retrieval_result(
        request_intent=_intent(),
        retrieval_result=_retrieval_result(),
        evidence_drafts=_evidence_drafts(),
        request=_request(),
        policy_confirmation_receipt_refs=[],
    )

    prompt_input = cast(dict[str, object], runtime.calls[0]["prompt_input"])
    _real_validator().validate(prompt_id="work_analysis.analyze", prompt_input=prompt_input)

    # B/C: no legacy root fields remain on the wire.
    for legacy_field in (
        "request_text",
        "retrieval_coverage",
        "resource_refs",
        "segment_refs",
        "evidence_refs",
        "evidence_drafts",
        "missing_information",
        "source_content_is_untrusted",
    ):
        assert legacy_field not in prompt_input


def test_normal_retrieval_path_dispatches_once_through_guarded_provider() -> None:
    """C: the exact shape this caller now sends reaches provider dispatch
    when routed through the real PromptInputGuardedProvider."""
    delegate = _FakeRawProvider()
    guarded = PromptInputGuardedProvider(delegate=delegate, validator=_real_validator())

    guarded.invoke_structured(
        prompt_ref=_WORK_ANALYSIS_ANALYZE_PROMPT_REF,
        prompt_input={
            "user_request": "Analyze risky follow-up work.",
            "request_intent": _intent(),
            "evidence": [],
            "availability_results": [],
            "policy_confirmation_receipt_refs": [],
        },
        output_schema=_dummy_output_schema(),
        runtime_policy=RuntimePolicy(),
        api_key=None,
    )

    assert delegate.calls == 1


def test_legacy_shaped_prompt_input_is_still_rejected_with_zero_dispatch() -> None:
    """D: the pre-fix legacy root-field shape must keep fail-closing --
    guards against silently reverting this alignment."""
    delegate = _FakeRawProvider()
    guarded = PromptInputGuardedProvider(delegate=delegate, validator=_real_validator())

    legacy_prompt_input = {
        "request_text": "x",
        "request_intent": _intent(),
        "retrieval_coverage": "SUFFICIENT",
        "resource_refs": [],
        "segment_refs": [],
        "evidence_refs": [],
        "evidence_drafts": [],
        "missing_information": [],
        "source_content_is_untrusted": True,
    }

    with pytest.raises(LLMInvocationError) as caught:
        guarded.invoke_structured(
            prompt_ref=_WORK_ANALYSIS_ANALYZE_PROMPT_REF,
            prompt_input=legacy_prompt_input,
            output_schema=_dummy_output_schema(),
            runtime_policy=RuntimePolicy(),
            api_key=None,
        )

    assert caught.value.code is LLMErrorCode.RUNTIME_VERSION_MISMATCH
    assert delegate.calls == 0


def test_confirmation_response_stays_within_allowed_roots() -> None:
    """E: same-owner resume confirmation_response is accepted by the real
    contract alongside the rest of the bounded projection."""
    runtime = _FakeStructuredLLMRuntime()
    runtime.queued.append(_llm_result({}))
    agent = _agent(runtime)

    agent.invoke_analyze_llm_from_retrieval_result(
        request_intent=_intent(),
        retrieval_result=_retrieval_result(),
        evidence_drafts=_evidence_drafts(),
        request=_request(),
        policy_confirmation_receipt_refs=[],
        confirmation_response={
            "schema_version": 1,
            "response_kind": "FREE_TEXT",
            "selected_option_ids": [],
            "free_text": "The follow-up task is the primary one.",
        },
    )

    prompt_input = cast(dict[str, object], runtime.calls[0]["prompt_input"])
    assert "confirmation_response" in prompt_input
    _real_validator().validate(prompt_id="work_analysis.analyze", prompt_input=prompt_input)


def test_policy_confirmation_receipt_refs_are_bounded_and_passed_through() -> None:
    """F: receipt refs are projected as a plain bounded list of ids, not the
    full receipt records."""
    runtime = _FakeStructuredLLMRuntime()
    runtime.queued.append(_llm_result({}))
    agent = _agent(runtime)

    agent.invoke_analyze_llm_from_retrieval_result(
        request_intent=_intent(),
        retrieval_result=_retrieval_result(),
        evidence_drafts=_evidence_drafts(),
        request=_request(),
        policy_confirmation_receipt_refs=["receipt-1", "receipt-2"],
    )

    prompt_input = cast(dict[str, object], runtime.calls[0]["prompt_input"])
    assert prompt_input["policy_confirmation_receipt_refs"] == ["receipt-1", "receipt-2"]
    _real_validator().validate(prompt_id="work_analysis.analyze", prompt_input=prompt_input)
