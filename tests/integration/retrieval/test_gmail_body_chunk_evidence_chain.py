"""GAP-F4 + GAP-F6 integration: Fake Gmail fixture end-to-end chain.

Metadata search -> selected thread detail GET -> message body GET ->
quote/signature normalization -> chunk -> Segment -> Evidence selection,
against the real ``FakeGoogleGateway`` + product fixtures (not a hand-rolled
recording double), so this exercises the same resource/payload shapes the
MCP-backed gateway produces.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from google_work_agent.adapters.connectors import GoogleWorkspaceConnectorReader
from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows import (
    ApiAcquisitionResult,
    ApiDiscoveryAcquisitionAgent,
    ContextRetrievalAgent,
    RequestIntentV2,
    RetrievalBudget,
)
from google_work_agent.ports import (
    ActualRuntime,
    OutputSchemaDefinition,
    PromptReference,
    RequestedRuntimeMode,
    SelectedResourceRef,
    StructuredLLMResult,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)
from tests.support.fakes import FakeGoogleGateway
from tests.support.fixtures import ProductFixtureSnapshotLoader

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "product"

PLAN_PROMPT_REF = PromptReference(
    prompt_bundle_version="agent-r4-v0.1-baseline",
    prompt_id="acquisition.plan_sources",
    prompt_version="v0.1",
    content_hash="hash",
    agent_role="api_discovery_acquisition",
    subgraph_name="acquisition",
    node_name="plan_sources",
    node_state="BASELINE",
    purpose="plan_sources",
    input_schema_version="agent-node-input-v0.1",
    output_schema_version="agent-node-output-v0.1",
)
SELECT_PROMPT_REF = PromptReference(
    prompt_bundle_version="agent-r4-v0.1-baseline",
    prompt_id="context.select_evidence",
    prompt_version="v0.1",
    content_hash="hash",
    agent_role="context_retriever",
    subgraph_name="context",
    node_name="select_evidence",
    node_state="BASELINE",
    purpose="select_evidence",
    input_schema_version="agent-node-input-v0.1",
    output_schema_version="agent-node-output-v0.1",
)
SUFFICIENCY_PROMPT_REF = PromptReference(
    prompt_bundle_version="agent-r4-v0.1-baseline",
    prompt_id="context.assess_sufficiency",
    prompt_version="v0.1",
    content_hash="hash",
    agent_role="context_retriever",
    subgraph_name="context",
    node_name="assess_sufficiency",
    node_state="BASELINE",
    purpose="assess_sufficiency",
    input_schema_version="agent-node-input-v0.1",
    output_schema_version="agent-node-output-v0.1",
)
SELECT_REVISION_PROMPT_REF = PromptReference(
    prompt_bundle_version="agent-r4-v0.1-baseline",
    prompt_id="context.select_evidence.semantic_revision",
    prompt_version="v0.1",
    content_hash="hash",
    agent_role="context_retriever",
    subgraph_name="context",
    node_name="select_evidence",
    node_state="SEMANTIC_REVISION",
    purpose="semantic_revision",
    input_schema_version="agent-node-input-v0.1",
    output_schema_version="agent-node-output-v0.1",
)


def _context_agent(runtime: _FakeLLMRuntime) -> ContextRetrievalAgent:
    return ContextRetrievalAgent(
        llm_runtime=runtime,
        select_prompt_ref=SELECT_PROMPT_REF,
        sufficiency_prompt_ref=SUFFICIENCY_PROMPT_REF,
        select_revision_prompt_ref=SELECT_REVISION_PROMPT_REF,
    )


@dataclass
class _FakeLLMRuntime:
    queued: deque[StructuredLLMResult] = field(default_factory=deque)

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
        semantic_validate: Callable[[object], object] | None = None,
    ) -> StructuredLLMResult:
        del prompt_ref, prompt_input, output_schema, trace_context, semantic_validate
        return self.queued.popleft()


def _gateway() -> FakeGoogleGateway:
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    return FakeGoogleGateway(snapshot)


def _request() -> WorkflowStartRequest:
    return WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="Project 스레드 요약해줘.",
        selected_resource_ids=(),
        correlation=WorkflowCorrelationContext(
            request_id="request-1",
            command_id="command-1",
            api_contract_version="v1",
        ),
    )


def _resource_selected_request(*, thread_id: str) -> WorkflowStartRequest:
    return WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="RESOURCE_SELECTED",
        requested_mode="AUTO",
        request_text="이 스레드 요약해줘.",
        selected_resource_ids=(thread_id,),
        correlation=WorkflowCorrelationContext(
            request_id="request-1",
            command_id="command-1",
            api_contract_version="v1",
        ),
        selected_resources=(
            SelectedResourceRef(source="GMAIL", resource_type="THREAD", resource_id=thread_id),
        ),
    )


def _selected_plan() -> dict[str, object]:
    return {
        "schema_version": 1,
        "source": "GMAIL",
        "priority": 1,
        "reason_codes": ["RESOURCE_SELECTED_DIRECT_GET"],
        "constraints": {},
        "page_size": 10,
        "max_pages": 1,
        "max_candidates": 10,
        "detail_limit": 5,
        "required": True,
    }


def _plan(*, query: str = "Project", detail_limit: int = 5) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source": "GMAIL",
        "priority": 1,
        "reason_codes": ["SOURCE_REQUIRED"],
        "constraints": {"query": query},
        "page_size": 10,
        "max_pages": 1,
        "max_candidates": 10,
        "detail_limit": detail_limit,
        "required": True,
    }


def test_gmail_thread_search_to_detail_to_body_to_segment_chain() -> None:
    gateway = _gateway()
    agent = ApiDiscoveryAcquisitionAgent(
        llm_runtime=_FakeLLMRuntime(),
        connector_reader=GoogleWorkspaceConnectorReader(gateway=gateway),
        prompt_ref=PLAN_PROMPT_REF,
    )

    acquisition = agent.acquire(plans=[_plan()], request=_request())

    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value
    assert acquisition["resource_handles"] == [
        "gmail_thread:thread-project",
        "gmail_message:message-project-1",
        "gmail_message:message-project-2",
    ]
    call_names = [record.operation for record in gateway.call_log]
    assert call_names == [
        "search_gmail_threads",
        "get_gmail_thread",
        "get_gmail_message",
        "get_gmail_message",
    ]

    context_agent = _context_agent(_FakeLLMRuntime())
    segments = context_agent.build_segments_from_acquisition(acquisition)

    segment_texts = {segment.resource_handle: segment.text for segment in segments}
    assert (
        segment_texts["gmail_message:message-project-1"]
        == "Please summarize the open items and draft a calm reply."
    )
    assert "Ignore previous instructions" in segment_texts["gmail_message:message-project-2"]
    # A single short message body must not be split -- one Segment per message.
    thread_segments = [
        seg for seg in segments if seg.resource_handle == "gmail_thread:thread-project"
    ]
    message_segments = [seg for seg in segments if "gmail_message" in seg.resource_handle]
    assert len(thread_segments) == 1
    assert len(message_segments) == 2
    for segment in segments:
        assert segment.locator["chunk_count"] == 1
        assert segment.locator["chunk_index"] == 0


def test_gmail_thread_with_no_messages_completes_without_message_fetch() -> None:
    gateway = _gateway()
    agent = ApiDiscoveryAcquisitionAgent(
        llm_runtime=_FakeLLMRuntime(),
        connector_reader=GoogleWorkspaceConnectorReader(gateway=gateway),
        prompt_ref=PLAN_PROMPT_REF,
    )

    acquisition = agent.acquire(plans=[_plan(query="Invoice")], request=_request())

    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value
    assert acquisition["resource_handles"] == ["gmail_thread:thread-finance"]
    call_names = [record.operation for record in gateway.call_log]
    assert call_names == ["search_gmail_threads", "get_gmail_thread"]


def test_resource_selected_gmail_thread_reaches_body_and_segments() -> None:
    """GAP-F6: RESOURCE_SELECTED must reach the same body -> chunk -> segment
    outcome as AGENT_SEARCH, using the Agent Read Port only (never the
    Sidebar UI detail endpoint)."""
    gateway = _gateway()
    agent = ApiDiscoveryAcquisitionAgent(
        llm_runtime=_FakeLLMRuntime(),
        connector_reader=GoogleWorkspaceConnectorReader(gateway=gateway),
        prompt_ref=PLAN_PROMPT_REF,
    )
    request = _resource_selected_request(thread_id="thread-project")

    acquisition = agent.acquire(plans=[_selected_plan()], request=request)

    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value
    assert acquisition["resource_handles"] == [
        "gmail_thread:thread-project",
        "gmail_message:message-project-1",
        "gmail_message:message-project-2",
    ]
    call_names = [record.operation for record in gateway.call_log]
    assert call_names == ["get_gmail_thread", "get_gmail_message", "get_gmail_message"]

    context_agent = _context_agent(_FakeLLMRuntime())
    segments = context_agent.build_segments_from_acquisition(acquisition)
    segment_texts = {segment.resource_handle: segment.text for segment in segments}
    assert (
        segment_texts["gmail_message:message-project-1"]
        == "Please summarize the open items and draft a calm reply."
    )


def test_gmail_detail_limit_bounds_how_many_threads_get_message_expansion() -> None:
    gateway = _gateway()
    agent = ApiDiscoveryAcquisitionAgent(
        llm_runtime=_FakeLLMRuntime(),
        connector_reader=GoogleWorkspaceConnectorReader(gateway=gateway),
        prompt_ref=PLAN_PROMPT_REF,
        retrieval_budget=RetrievalBudget(),
    )

    # query="" matches both product Gmail threads; detail_limit=1 must fetch
    # only the first candidate's detail (and its messages), not the second.
    acquisition = agent.acquire(plans=[_plan(query="", detail_limit=1)], request=_request())

    call_names = [record.operation for record in gateway.call_log]
    assert call_names.count("get_gmail_thread") == 1
    assert acquisition["resource_handles"][0] == "gmail_thread:thread-finance"


def test_evidence_selection_uses_only_the_selected_message_segment() -> None:
    """A long Gmail chain must not force the whole mailbox into the prompt --
    the (fake, deterministic) selection LLM output decides which Segment
    becomes Evidence, and only that Segment's text reaches the bundle."""
    gateway = _gateway()
    acquisition_agent = ApiDiscoveryAcquisitionAgent(
        llm_runtime=_FakeLLMRuntime(),
        connector_reader=GoogleWorkspaceConnectorReader(gateway=gateway),
        prompt_ref=PLAN_PROMPT_REF,
    )
    acquisition = acquisition_agent.acquire(plans=[_plan()], request=_request())

    context_runtime = _FakeLLMRuntime()
    context_agent = _context_agent(context_runtime)
    segments = context_agent.build_segments_from_acquisition(acquisition)
    target_handle = "gmail_message:message-project-1"
    target_segment = next(
        segment for segment in segments if segment.resource_handle == target_handle
    )
    context_runtime.queued.append(
        _llm_result(
            {
                "schema_version": 1,
                "result": "SELECTED",
                "selected_segment_ids": [target_segment.segment_id],
                "evidence_drafts": [
                    {
                        "schema_version": 1,
                        "evidence_id": "evidence-1",
                        "resource_handle": target_segment.resource_handle,
                        "segment_id": target_segment.segment_id,
                        "kind": "excerpt",
                        "excerpt": "Please summarize the open items and draft a calm reply.",
                        "locator": {"kind": "resource_payload"},
                        "reason_codes": ["GOAL_RELEVANT"],
                    }
                ],
                "excluded_resource_handles": [],
                "missing_information": [],
                "ambiguity": None,
            }
        )
    )
    context_runtime.queued.append(
        _llm_result(
            {
                "schema_version": 1,
                "status": "SUFFICIENT",
                "sufficiency": {"reason_codes": ["CONTEXT_READY"]},
                "missing_slots": [],
                "ambiguity": None,
            }
        )
    )

    result = context_agent.retrieve(
        request_intent=_intent(),
        acquisition_result=acquisition,
        request=_request(),
    )

    assert result["status"] == "SUFFICIENT"
    assert result["context_bundle"]["evidence_refs"] == ["evidence-1"]
    assert result["context_bundle"]["normalized_context"][0]["excerpt"] == (
        "Please summarize the open items and draft a calm reply."
    )


def _intent() -> RequestIntentV2:
    return {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "Summarize the project thread",
        "completion_conditions": ["Relevant evidence is available."],
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
