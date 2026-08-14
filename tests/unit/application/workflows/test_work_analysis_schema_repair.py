"""Regression tests for the work_analysis Schema Repair boundary.

Covers the READ-runtime crash traced in this session: a semantically
invalid ``work_analysis.analyze`` output (e.g. a non-string ``resource_refs``
entry) used to raise ``WorkAnalysisValidationError`` straight out of
``WorkAnalysisAgent.analyze`` -- unreachable by ``_validate_or_repair`` --
instead of going through the same Schema Repair boundary JSON-schema-shape
failures already use. These tests exercise the real
``LLMRuntimeService`` + ``PromptRepairSchemaRepairer`` + a fake API
transport (not fakes of the repair mechanism itself), proving the repair
round-trip actually happens end to end once a subgraph's ``.repair`` prompt
slot is ``RUNTIME_ACTIVE``.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from tests.support.fakes import FakeAPIProviderTransport, FakeHardwareProbe, FakeKeyring
from tests.support.prompt_manifests import (
    write_manifest_with_overrides,
    write_runtime_active_manifest,
)

from google_work_agent.adapters.llm import (
    APIProviderConnectionService,
    ApiStructuredLLMProvider,
    CredentialStorageMode,
    DeterministicLLMRuntimeRouter,
    LLMCredentialService,
    LLMRuntimeStatusService,
    OllamaStructuredLLMProvider,
    SessionMemorySecretStore,
)
from google_work_agent.adapters.runtime import AppSettings
from google_work_agent.application.llm import LLMRuntimeService, PromptRepairSchemaRepairer
from google_work_agent.application.workflows import (
    AnalysisResult,
    ContextRetrievalResultV1,
    RequestIntentV2,
    WorkAnalysisAgent,
    validate_work_analysis_result_v1,
)
from google_work_agent.application.workflows.work_analysis import WorkAnalysisValidationError
from google_work_agent.ports import (
    LLMErrorCode,
    LLMInvocationError,
    ProviderResponsePayload,
    RuntimePolicy,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)

# Duplicated (rather than imported) from test_work_analysis.py: that module
# has no __init__.py sibling package marker, so a relative/package import
# from this file is not reliable under pytest's rootdir-based collection.
# Kept in sync in spirit only -- these are plain fixture builders with no
# shared state.


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
        "constraints": [],
        "ambiguity": {
            "requires_confirmation": False,
            "reason_codes": [],
            "missing_fields": [],
        },
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "REQUIRED",
    }


def _context_result(
    *,
    excerpt: str = "Kim is waiting for the follow-up task.",
) -> ContextRetrievalResultV1:
    return {
        "schema_version": 1,
        "status": "SUFFICIENT",
        "context_bundle": {
            "schema_version": 1,
            "resource_refs": [
                {
                    "resource_handle": "gmail_thread:thread-kim",
                    "source": "GMAIL",
                    "resource_type": "gmail_thread",
                    "resource_id": "thread-kim",
                    "parent_id": None,
                    "version": "1",
                }
            ],
            "segment_refs": [
                {
                    "segment_id": "seg-1",
                    "resource_handle": "gmail_thread:thread-kim",
                    "source": "GMAIL",
                    "locator": {"kind": "resource_payload"},
                }
            ],
            "evidence_refs": ["evidence-1"],
            "normalized_context": [
                {
                    "evidence_id": "evidence-1",
                    "resource_handle": "gmail_thread:thread-kim",
                    "segment_id": "seg-1",
                    "kind": "excerpt",
                    "excerpt": excerpt,
                }
            ],
            "missing_information": [],
            "ambiguity": None,
        },
        "evidence_drafts": [
            {
                "schema_version": 1,
                "evidence_id": "evidence-1",
                "resource_handle": "gmail_thread:thread-kim",
                "segment_id": "seg-1",
                "kind": "excerpt",
                "excerpt": excerpt,
                "locator": {"kind": "resource_payload"},
                "reason_codes": ["GOAL_RELEVANT"],
            }
        ],
        "selected_segment_ids": ["seg-1"],
        "excluded_resource_handles": [],
        "missing_slots": [],
        "additional_acquisition_request": None,
        "sufficiency": {
            "schema_version": 1,
            "reason_codes": ["CONTEXT_READY"],
            "summary": "Context is ready for analysis.",
        },
        "llm_provider_result": {"provider": "fake"},
    }


def _finding(finding_id: str, kind: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "finding_id": finding_id,
        "kind": kind,
        "statement": "Kim's thread is related to the follow-up task.",
        "evidence_refs": ["evidence-1"],
        "resource_refs": ["gmail_thread:thread-kim"],
        "segment_refs": ["seg-1"],
        "related_resource_handles": ["gmail_thread:thread-kim"],
        "reason_codes": ["EVIDENCE_SUPPORTED"],
    }


def _analysis_output(
    status: str,
    *,
    findings: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if findings is None:
        findings = [_finding("finding-1", "RELATIONSHIP")]
    return {
        "schema_version": 1,
        "status": status,
        "summary": "Evidence shows a follow-up relationship.",
        "findings": findings,
        "missing_information": [],
        "confirmation": None,
        "blockers": [],
        "evidence_refs": ["evidence-1"],
        "resource_refs": _context_result()["context_bundle"]["resource_refs"],
        "segment_refs": _context_result()["context_bundle"]["segment_refs"],
    }


@pytest.mark.parametrize(
    "invalid_resource_refs",
    [[123], [{"id": "gmail_thread:thread-kim"}], [None]],
    ids=["integer", "object", "null"],
)
def test_finding_resource_refs_must_be_strings(invalid_resource_refs: list[object]) -> None:
    """The exact shape observed in production: a schema-shape-valid but
    semantically-invalid ``resource_refs`` entry (findings items are only
    checked as ``{"type": "object"}`` at the JSON-schema level -- see
    ``WORK_ANALYSIS_OUTPUT_SCHEMA`` in work_analysis.py)."""
    finding = _finding("finding-1", "RELATIONSHIP")
    finding["resource_refs"] = invalid_resource_refs
    output = _analysis_output(AnalysisResult.COMPLETE.value, findings=[finding])

    with pytest.raises(WorkAnalysisValidationError, match=r"resource_refs\[0\] must be string"):
        validate_work_analysis_result_v1(output, context_result=_context_result())


def _real_llm_runtime(
    api_transport: FakeAPIProviderTransport,
    *,
    manifest_path: Path,
) -> LLMRuntimeService:
    credential_service = LLMCredentialService(
        provider_name="generic",
        environment="DEVELOPMENT",
        keyring_store=FakeKeyring(),
        session_store=SessionMemorySecretStore(),
    )
    credential_service.store(api_key="key-1", mode=CredentialStorageMode.KEYRING)
    settings = AppSettings(
        deployment_profile="API_ONLY",
        requested_runtime_mode="API_LLM",
        external_llm_consent=True,
    )
    from tests.support.fakes import FakeOllamaTransport, approved_model

    status_service = LLMRuntimeStatusService(
        build_profile="API_ONLY",
        credential_service=credential_service,
        api_connection_service=APIProviderConnectionService(api_transport),
        hardware_probe=FakeHardwareProbe(),
        ollama_probe=type(
            "_Probe",
            (),
            {"probe": lambda self, endpoint, approved_model: None},  # noqa: ARG005
        )(),
        approved_models={approved_model().model_id: approved_model()},
        runtime_policy=RuntimePolicy(),
    )
    return LLMRuntimeService(
        settings_service=lambda: settings,
        status_service=status_service,
        credential_service=credential_service,
        api_provider=ApiStructuredLLMProvider(
            provider_name="generic-api",
            transport=api_transport,
            model="api-model",
        ),
        ollama_provider_factory=lambda model, current_settings: OllamaStructuredLLMProvider(
            provider_name="ollama",
            transport=FakeOllamaTransport(),
            endpoint=current_settings.ollama_endpoint or "http://127.0.0.1:11434",
            model_id=model.model_id,
        ),
        router=DeterministicLLMRuntimeRouter(),
        runtime_policy=RuntimePolicy(structured_output_repair_budget=1),
        schema_repairer=PromptRepairSchemaRepairer(manifest_path=manifest_path),
    )


def _queue(api_transport: FakeAPIProviderTransport, payload: object) -> None:
    api_transport.queued_payloads.append(
        ProviderResponsePayload(
            content=payload,
            model="api-model",
            provider_request_id="req-1",
            input_tokens=5,
            output_tokens=4,
            latency_ms=10,
        )
    )


def test_invalid_first_output_is_repaired_and_run_continues(tmp_path: Path) -> None:
    """First real call: resource_refs=[123] (semantically invalid). Second
    real call (the work_analysis.analyze.repair prompt, once promoted
    RUNTIME_ACTIVE): a corrected, valid payload. The agent must return the
    repaired result without the caller ever seeing a raised validation
    error."""
    manifest_path = write_runtime_active_manifest(
        tmp_path, prompt_ids=["work_analysis.analyze", "work_analysis.analyze.repair"]
    )
    api_transport = FakeAPIProviderTransport()

    bad_finding = _finding("finding-1", "RELATIONSHIP")
    bad_finding["resource_refs"] = [123]
    _queue(api_transport, _analysis_output(AnalysisResult.COMPLETE.value, findings=[bad_finding]))
    _queue(api_transport, _analysis_output(AnalysisResult.COMPLETE.value))

    runtime = _real_llm_runtime(api_transport, manifest_path=manifest_path)
    agent = WorkAnalysisAgent(llm_runtime=runtime, manifest_path=manifest_path)

    result = agent.analyze(
        request_intent=_intent(), context_result=_context_result(), request=_request()
    )

    assert result["status"] == AnalysisResult.COMPLETE.value
    assert result["findings"][0]["resource_refs"] == ["gmail_thread:thread-kim"]
    invoke_calls = [c for c in api_transport.invocations if c["kind"] == "invoke"]
    assert len(invoke_calls) == 2
    assert invoke_calls[0]["prompt_id"] == "work_analysis.analyze"
    assert invoke_calls[1]["prompt_id"] == "work_analysis.analyze.repair"
    repair_input = cast(dict[str, object], invoke_calls[1]["prompt_input"])
    assert repair_input["attempt_no"] == 1
    assert repair_input["max_attempts"] == 1
    validator_errors = cast(list[str], repair_input["validator_errors"])
    assert any("resource_refs" in message for message in validator_errors)


def test_still_invalid_after_repair_raises_typed_error_not_unlimited_retry(
    tmp_path: Path,
) -> None:
    """Repair gets exactly one try. If the repaired candidate is still
    semantically invalid, the caller must see one clean, typed,
    OUTPUT_SCHEMA_INVALID LLMInvocationError -- never a second repair
    attempt and never the raw WorkAnalysisValidationError escaping."""
    manifest_path = write_runtime_active_manifest(
        tmp_path, prompt_ids=["work_analysis.analyze", "work_analysis.analyze.repair"]
    )
    api_transport = FakeAPIProviderTransport()

    first_bad = _finding("finding-1", "RELATIONSHIP")
    first_bad["resource_refs"] = [123]
    second_bad = _finding("finding-1", "RELATIONSHIP")
    second_bad["resource_refs"] = [None]
    _queue(api_transport, _analysis_output(AnalysisResult.COMPLETE.value, findings=[first_bad]))
    _queue(api_transport, _analysis_output(AnalysisResult.COMPLETE.value, findings=[second_bad]))

    runtime = _real_llm_runtime(api_transport, manifest_path=manifest_path)
    agent = WorkAnalysisAgent(llm_runtime=runtime, manifest_path=manifest_path)

    with pytest.raises(LLMInvocationError) as excinfo:
        agent.analyze(
            request_intent=_intent(), context_result=_context_result(), request=_request()
        )
    assert excinfo.value.code is LLMErrorCode.OUTPUT_SCHEMA_INVALID
    invoke_calls = [c for c in api_transport.invocations if c["kind"] == "invoke"]
    assert len(invoke_calls) == 2, "must not attempt a second repair round"


def test_repair_prompt_still_draft_fails_closed_without_using_unapproved_prompt(
    tmp_path: Path,
) -> None:
    """Documents the actual current repo state: every ``*.repair`` slot in
    the canonical manifest (including work_analysis.analyze.repair) is
    still DRAFT -- Node DEV -> Node HOLDOUT -> G01 Safety Gate has not
    promoted it. The repairer must refuse to use it rather than silently
    activating an unapproved prompt, and the failure must still be the
    same typed, catchable LLMInvocationError."""
    manifest_path = write_manifest_with_overrides(
        tmp_path,
        active_prompt_ids={"work_analysis.analyze"},
        draft_prompt_ids={"work_analysis.analyze.repair"},
    )
    api_transport = FakeAPIProviderTransport()
    bad_finding = _finding("finding-1", "RELATIONSHIP")
    bad_finding["resource_refs"] = [123]
    _queue(api_transport, _analysis_output(AnalysisResult.COMPLETE.value, findings=[bad_finding]))

    runtime = _real_llm_runtime(api_transport, manifest_path=manifest_path)
    agent = WorkAnalysisAgent(llm_runtime=runtime, manifest_path=manifest_path)

    with pytest.raises(LLMInvocationError) as excinfo:
        agent.analyze(
            request_intent=_intent(), context_result=_context_result(), request=_request()
        )
    assert excinfo.value.code is LLMErrorCode.OUTPUT_SCHEMA_INVALID
    invoke_calls = [c for c in api_transport.invocations if c["kind"] == "invoke"]
    assert len(invoke_calls) == 1, "a DRAFT repair prompt must never be dispatched"


def test_valid_first_output_never_invokes_repair(tmp_path: Path) -> None:
    manifest_path = write_runtime_active_manifest(
        tmp_path, prompt_ids=["work_analysis.analyze", "work_analysis.analyze.repair"]
    )
    api_transport = FakeAPIProviderTransport()
    _queue(api_transport, _analysis_output(AnalysisResult.COMPLETE.value))

    runtime = _real_llm_runtime(api_transport, manifest_path=manifest_path)
    agent = WorkAnalysisAgent(llm_runtime=runtime, manifest_path=manifest_path)

    result = agent.analyze(
        request_intent=_intent(), context_result=_context_result(), request=_request()
    )

    assert result["status"] == AnalysisResult.COMPLETE.value
    invoke_calls = [c for c in api_transport.invocations if c["kind"] == "invoke"]
    assert len(invoke_calls) == 1
