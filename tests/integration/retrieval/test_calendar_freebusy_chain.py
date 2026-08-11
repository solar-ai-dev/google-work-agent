"""GAP-F7 integration: Calendar FreeBusy call-gating and Analysis handoff.

Exercises the deterministic, plan-gated FreeBusy Read against the real
``FakeGoogleGateway`` + product fixtures, and verifies the normalized
summary (not raw Google FreeBusy JSON) is what reaches Context Retrieval
Segment text.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows import (
    ApiAcquisitionResult,
    ApiDiscoveryAcquisitionAgent,
    ContextRetrievalAgent,
    RequestIntentV1,
)
from google_work_agent.ports import (
    OutputSchemaDefinition,
    PromptReference,
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
    ) -> StructuredLLMResult:
        del prompt_ref, prompt_input, output_schema, trace_context
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
        request_text="이번 주에 가능한 시간 찾아줘.",
        selected_resource_ids=(),
        correlation=WorkflowCorrelationContext(
            request_id="request-1",
            command_id="command-1",
            api_contract_version="v1",
        ),
    )


def _availability_intent() -> RequestIntentV1:
    return {
        "schema_version": 2,
        "goal": {
            "summary": "이번 주에 가능한 시간 찾아줘",
            "user_visible_objective": "이번 주에 가능한 시간 찾아줘",
        },
        "completion_criteria": ["빈 시간대를 찾는다."],
        "semantic_constraints": {
            "topics": [],
            "people": [],
            "time": [],
            "sources": [{"source": "CALENDAR", "mention": "calendar", "confidence": "HIGH"}],
            "status_or_state": [],
            "negative_constraints": [],
            "policy_or_safety_constraints": [],
        },
        "ambiguity": {"is_ambiguous": False, "items": []},
        "unsupported_scope": {"is_unsupported": False, "reason_code": None, "explanation": None},
    }


def _simple_listing_intent() -> RequestIntentV1:
    return {
        "schema_version": 2,
        "goal": {
            "summary": "내일 일정 알려줘",
            "user_visible_objective": "내일 일정 알려줘",
        },
        "completion_criteria": ["오늘 일정 목록을 보여준다."],
        "semantic_constraints": {
            "topics": [],
            "people": [],
            "time": [],
            "sources": [{"source": "CALENDAR", "mention": "calendar", "confidence": "HIGH"}],
            "status_or_state": [],
            "negative_constraints": [],
            "policy_or_safety_constraints": [],
        },
        "ambiguity": {"is_ambiguous": False, "items": []},
        "unsupported_scope": {"is_unsupported": False, "reason_code": None, "explanation": None},
    }


def _temporal_query(
    *,
    relation: str = "ABSOLUTE",
    relative_unit: str | None = None,
    relative_offset: int | None = None,
    weekday: str | None = None,
    daypart: str | None = None,
    absolute_start: str | None = None,
    absolute_end: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "relation": relation,
        "relative_unit": relative_unit,
        "relative_offset": relative_offset,
        "weekday": weekday,
        "daypart": daypart,
        "absolute_start": absolute_start,
        "absolute_end": absolute_end,
    }


def _plan(
    *,
    calendar_read_mode: str,
    temporal_query: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 2,
        "source": "CALENDAR",
        "priority": 1,
        "reason_codes": ["SOURCE_REQUIRED"],
        "constraints": {"calendar_id": "calendar-primary"},
        "page_size": 10,
        "max_pages": 1,
        "max_candidates": 10,
        "detail_limit": 5,
        "required": True,
        "calendar_read_mode": calendar_read_mode,
        "temporal_query": temporal_query,
    }


def test_availability_required_request_calls_freebusy_once_and_hands_off_summary() -> None:
    """FreeBusy gating comes only from the typed SourceFetchPlan
    calendar_read_mode/temporal_query fields, never from parsing
    request_intent text -- see the sibling ``_does_not_call_freebusy`` test
    for the negative case this is paired with."""
    gateway = _gateway()
    agent = ApiDiscoveryAcquisitionAgent(
        llm_runtime=_FakeLLMRuntime(),
        gateway=gateway,
        prompt_ref=PLAN_PROMPT_REF,
    )

    acquisition = agent.acquire(
        plans=[
            _plan(
                calendar_read_mode="EVENTS_AND_FREEBUSY",
                temporal_query=_temporal_query(
                    absolute_start="2026-11-01T00:00:00-08:00",
                    absolute_end="2026-11-02T00:00:00-08:00",
                ),
            )
        ],
        request=_request(),
        request_intent=_availability_intent(),
    )

    call_names = [record.operation for record in gateway.call_log]
    assert call_names.count("query_freebusy") == 1
    freebusy_handles = [
        handle
        for handle in acquisition["resource_handles"]
        if handle.startswith("calendar_freebusy:")
    ]
    assert len(freebusy_handles) == 1

    context_agent = ContextRetrievalAgent(
        llm_runtime=_FakeLLMRuntime(),
        select_prompt_ref=SELECT_PROMPT_REF,
        sufficiency_prompt_ref=SUFFICIENCY_PROMPT_REF,
        select_revision_prompt_ref=SELECT_REVISION_PROMPT_REF,
    )
    segments = context_agent.build_segments_from_acquisition(acquisition)
    freebusy_segment = next(
        segment for segment in segments if segment.resource_handle.startswith("calendar_freebusy:")
    )
    # Normalized, code-authored sentence -- never raw Google FreeBusy JSON.
    assert freebusy_segment.text.startswith("calendar-primary busy intervals between")
    assert "{" not in freebusy_segment.text
    assert "2026-11-01T08:00:00-07:00" in freebusy_segment.text


def test_simple_event_listing_does_not_call_freebusy() -> None:
    gateway = _gateway()
    agent = ApiDiscoveryAcquisitionAgent(
        llm_runtime=_FakeLLMRuntime(),
        gateway=gateway,
        prompt_ref=PLAN_PROMPT_REF,
    )

    acquisition = agent.acquire(
        plans=[_plan(calendar_read_mode="EVENTS_ONLY")],
        request=_request(),
        request_intent=_simple_listing_intent(),
    )

    call_names = [record.operation for record in gateway.call_log]
    assert "query_freebusy" not in call_names
    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value


def test_invalid_time_range_skips_freebusy_without_calling_google() -> None:
    gateway = _gateway()
    agent = ApiDiscoveryAcquisitionAgent(
        llm_runtime=_FakeLLMRuntime(),
        gateway=gateway,
        prompt_ref=PLAN_PROMPT_REF,
    )

    # Typed signal present, but end before start -> TimeRange construction
    # fails -> deterministic skip (not a text-classification decision).
    acquisition = agent.acquire(
        plans=[
            _plan(
                calendar_read_mode="EVENTS_AND_FREEBUSY",
                temporal_query=_temporal_query(
                    absolute_start="2026-11-02T00:00:00-08:00",
                    absolute_end="2026-11-01T00:00:00-08:00",
                ),
            )
        ],
        request=_request(),
        request_intent=_availability_intent(),
    )

    call_names = [record.operation for record in gateway.call_log]
    assert "query_freebusy" not in call_names
    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value
    assert "CALENDAR:INVALID_TEMPORAL_QUERY" in acquisition["missing_slots"]
