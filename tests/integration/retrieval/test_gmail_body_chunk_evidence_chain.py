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

from google_work_agent.application.agents.retrieval.assess_sufficiency import (
    assess_sufficiency,
)
from google_work_agent.application.agents.retrieval.normalize_segments import (
    normalize_segments,
)
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import (
    rag_retrieve_rerank,
)
from google_work_agent.application.agents.retrieval.select_evidence import (
    materialize_evidence_drafts,
    select_evidence,
)
from google_work_agent.application.orchestration.api_acquisition import (
    ApiDiscoveryAcquisitionAgent,
    RetrievalBudget,
)
from google_work_agent.application.orchestration.connector_read_projection import (
    ConnectorReadProjection,
)
from google_work_agent.application.orchestration.contracts import (
    ApiAcquisitionResult,
)
from google_work_agent.application.orchestration.handoff_contracts import RequestIntentV2
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    build_default_run_budget,
)
from google_work_agent.ports.llm import (
    ActualRuntime,
    OutputSchemaDefinition,
    PromptReference,
    RequestedRuntimeMode,
    StructuredLLMResult,
)
from google_work_agent.ports.system.contracts.observability import ObservabilityContext
from google_work_agent.ports.system.contracts.workflow_execution import (
    SelectedResourceRef,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)
from tests.support.fakes import FakeGoogleGateway
from tests.support.fixtures import ProductFixtureSnapshotLoader
from tests.support.google_gateway_connector_ports import GoogleGatewayConnectorReadPort

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
        run_budget=build_default_run_budget(),
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
        run_budget=build_default_run_budget(),
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
        connector_reader=ConnectorReadProjection(
            GoogleGatewayConnectorReadPort(gateway), load_signed_tool_registry()
        ),
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

    segments = normalize_segments(acquisition)

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
        connector_reader=ConnectorReadProjection(
            GoogleGatewayConnectorReadPort(gateway), load_signed_tool_registry()
        ),
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
        connector_reader=ConnectorReadProjection(
            GoogleGatewayConnectorReadPort(gateway), load_signed_tool_registry()
        ),
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

    segments = normalize_segments(acquisition)
    segment_texts = {segment.resource_handle: segment.text for segment in segments}
    assert (
        segment_texts["gmail_message:message-project-1"]
        == "Please summarize the open items and draft a calm reply."
    )


def test_gmail_detail_limit_bounds_how_many_threads_get_message_expansion() -> None:
    gateway = _gateway()
    agent = ApiDiscoveryAcquisitionAgent(
        llm_runtime=_FakeLLMRuntime(),
        connector_reader=ConnectorReadProjection(
            GoogleGatewayConnectorReadPort(gateway), load_signed_tool_registry()
        ),
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
        connector_reader=ConnectorReadProjection(
            GoogleGatewayConnectorReadPort(gateway), load_signed_tool_registry()
        ),
        prompt_ref=PLAN_PROMPT_REF,
    )
    acquisition = acquisition_agent.acquire(plans=[_plan()], request=_request())

    context_runtime = _FakeLLMRuntime()
    segments = normalize_segments(acquisition)
    target_handle = "gmail_message:message-project-1"
    target_segment = next(
        segment for segment in segments if segment.resource_handle == target_handle
    )
    context_runtime.queued.append(
        _llm_result(
            {
                "schema_version": 2,
                "selected_segment_ids": [target_segment.segment_id],
                "evidence_drafts": [
                    {
                        "segment_id": target_segment.segment_id,
                        "role": "SUPPORTS",
                        "relevance_reason": "Directly answers the summary request.",
                    }
                ],
                "excluded_segment_ids": [],
            }
        )
    )
    context_runtime.queued.append(
        _llm_result(
            {
                "schema_version": 2,
                "status": "SUFFICIENT",
                "issues": [],
            }
        )
    )

    ranked = rag_retrieve_rerank(segments, request_intent=_intent(), top_k=24)
    selection, budget = select_evidence(
        llm_runtime=context_runtime,
        prompt_ref=SELECT_PROMPT_REF,
        revision_prompt_ref=SELECT_REVISION_PROMPT_REF,
        trace_context=_trace(),
        request_intent=_intent(),
        rag_candidates=ranked,
        segments=segments,
        retry_budget=build_default_run_budget(),
    )
    evidence = materialize_evidence_drafts(selection, segments=segments)
    result = assess_sufficiency(
        llm_runtime=context_runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        trace_context=_trace(),
        request_intent=_intent(),
        tool_route_plan=None,
        acquisition_result=acquisition,
        evidence_drafts=evidence,
        retry_budget=budget,
    )

    assert result["status"] == "SUFFICIENT"
    assert [item["evidence_id"] for item in evidence] == [
        f"evidence-{target_segment.segment_id}"
    ]
    assert evidence[0]["excerpt"] == (
        "Please summarize the open items and draft a calm reply."
    )


def _trace() -> ObservabilityContext:
    return ObservabilityContext(
        request_id="request-1",
        command_id="command-1",
        conversation_id="conversation-1",
        run_id="run-1",
        langgraph_thread_id="thread-1",
        llm_call_id="run-1:retrieval",
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
