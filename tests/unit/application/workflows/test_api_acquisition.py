from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TypedDict, cast

import pytest

from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)
from google_work_agent.application.orchestration.api_acquisition import (
    ApiDiscoveryAcquisitionAgent,
    RetrievalBudget,
    SourceName,
    SourcePlanningValidationError,
    build_source_planning_clarification_question,
    validate_acquisition_result_v1,
)
from google_work_agent.application.orchestration.connector_read_models import (
    PlannedConnectorRead,
)
from google_work_agent.application.orchestration.connector_read_projection import (
    ConnectorReadProjection,
)
from google_work_agent.application.orchestration.contracts import (
    AdditionalAcquisitionRequestV1,
    ApiAcquisitionResult,
    ApiPlanningResult,
    WorkflowPhase,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    CalendarReadMode,
    Daypart,
    RelativeUnit,
    RequestIntentV2,
    SourceFetchPlanV1,
    TemporalQueryV1,
    TemporalRelation,
    Weekday,
)
from google_work_agent.application.tool_registry import load_signed_tool_registry
from google_work_agent.ports.connector.connector_read_port import (
    ConnectorReadResultV1,
    JsonValue,
)
from google_work_agent.ports.connector.contracts import ValidatedConnectorToolBindingV1
from google_work_agent.ports.connector.contracts.google_workspace import (
    FreeBusyCalendar,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    ResourcePage,
    ResourceSnapshot,
    ResourceType,
    TimeRange,
)
from google_work_agent.ports.llm import (
    ActualRuntime,
    LLMErrorCode,
    LLMInvocationError,
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

PROMPT_REF = PromptReference(
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
DEFAULT_TEST_RETRIEVAL_BUDGET = RetrievalBudget()


def test_connector_reader_rejects_read_outside_frozen_tool_ids() -> None:
    reader = _connector_reader(RecordingGoogleGateway())
    request = PlannedConnectorRead(
        plan=_plan("TASKS", {}),
        selected_resources=(),
        prefer_selected_resources=False,
        remaining_budget=DEFAULT_TEST_RETRIEVAL_BUDGET.as_remaining(),
        now_ms=0,
        timezone="Asia/Seoul",
        allowed_read_tool_ids=frozenset({"tasks_list_tasks", "tasks_get_task"}),
    )

    with pytest.raises(PermissionError, match="outside frozen input route"):
        reader.read(request)


class LLMCall(TypedDict):
    prompt_ref: PromptReference
    prompt_input: dict[str, object]
    output_schema: OutputSchemaDefinition
    trace_context: ObservabilityContext
    semantic_validate: Callable[[object], object] | None


@dataclass
class FakeLLMRuntime:
    queued: deque[StructuredLLMResult | Exception] = field(default_factory=deque)
    calls: list[LLMCall] = field(default_factory=list)

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
        semantic_validate: Callable[[object], object] | None = None,
    ) -> StructuredLLMResult:
        self.calls.append(
            {
                "prompt_ref": prompt_ref,
                "prompt_input": dict(prompt_input),
                "output_schema": output_schema,
                "trace_context": trace_context,
                "semantic_validate": semantic_validate,
            }
        )
        result = self.queued.popleft()
        if isinstance(result, Exception):
            raise result
        return result


class RecordingGoogleGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.faults: dict[str, GoogleWorkspaceGatewayError] = {}
        self.gmail_threads = {
            "thread-kim": _snapshot(
                ResourceType.GMAIL_THREAD,
                "thread-kim",
                title="김대리 메일",
                subject="김대리 메일",
            )
        }
        self.task_lists = {
            "task-list-default": _snapshot(
                ResourceType.TASK_LIST,
                "task-list-default",
                title="Tasks",
            )
        }
        self.tasks = {
            "task-1": _snapshot(
                ResourceType.TASK,
                "task-1",
                parent_id="task-list-default",
                title="이번 주 할 일",
            )
        }
        self.calendars = {
            "calendar-primary": _snapshot(ResourceType.CALENDAR, "calendar-primary", title="기본")
        }
        self.events = {
            "event-1": _snapshot(
                ResourceType.CALENDAR_EVENT,
                "event-1",
                parent_id="calendar-primary",
                title="이번 주 회의",
            )
        }
        self.gmail_messages: dict[str, ResourceSnapshot] = {}
        self.freebusy: dict[str, tuple[FreeBusyCalendar, ...]] = {}

    def queue_fault(self, operation: str, code: GoogleWorkspaceErrorCode) -> None:
        self.faults[operation] = GoogleWorkspaceGatewayError(
            code=code,
            message=f"fault: {code.value}",
            delivered=True,
            mutated=False,
        )

    def search_gmail_threads(
        self,
        *,
        query: str,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        self._maybe_fault("search_gmail_threads")
        self.calls.append(
            (
                "search_gmail_threads",
                {"query": query, "page_token": page_token, "page_size": page_size},
            )
        )
        return ResourcePage(
            items=tuple(self.gmail_threads.values())[:page_size],
            next_page_token=None,
        )

    def get_gmail_thread(self, *, thread_id: str) -> ResourceSnapshot:
        self._maybe_fault("get_gmail_thread")
        self.calls.append(("get_gmail_thread", {"thread_id": thread_id}))
        return self.gmail_threads[thread_id]

    def get_gmail_message(self, *, message_id: str) -> ResourceSnapshot:
        self._maybe_fault("get_gmail_message")
        self.calls.append(("get_gmail_message", {"message_id": message_id}))
        return self.gmail_messages[message_id]

    def create_gmail_draft(
        self,
        *,
        payload: dict[str, object],
        claim_context: dict[str, object] | None = None,
    ) -> ResourceSnapshot:
        raise NotImplementedError

    def update_gmail_draft(
        self,
        *,
        draft_id: str,
        payload: dict[str, object],
        claim_context: dict[str, object] | None = None,
    ) -> ResourceSnapshot:
        raise NotImplementedError

    def get_gmail_draft(self, *, draft_id: str) -> ResourceSnapshot:
        raise NotImplementedError

    def send_gmail(
        self,
        *,
        draft_id: str,
        recovery_fingerprint: str | None,
        claim_context: dict[str, object] | None = None,
    ) -> ResourceSnapshot:
        raise NotImplementedError

    def list_task_lists(self, *, page_token: str | None, page_size: int) -> ResourcePage:
        self._maybe_fault("list_task_lists")
        self.calls.append(("list_task_lists", {"page_token": page_token, "page_size": page_size}))
        return ResourcePage(items=tuple(self.task_lists.values())[:page_size], next_page_token=None)

    def list_tasks(
        self,
        *,
        task_list_id: str,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        self._maybe_fault("list_tasks")
        self.calls.append(
            (
                "list_tasks",
                {
                    "task_list_id": task_list_id,
                    "page_token": page_token,
                    "page_size": page_size,
                },
            )
        )
        return ResourcePage(items=tuple(self.tasks.values())[:page_size], next_page_token=None)

    def get_task(self, *, task_list_id: str, task_id: str) -> ResourceSnapshot:
        self._maybe_fault("get_task")
        self.calls.append(("get_task", {"task_list_id": task_list_id, "task_id": task_id}))
        return self.tasks[task_id]

    def create_task(
        self,
        *,
        task_list_id: str,
        payload: dict[str, object],
        claim_context: dict[str, object] | None = None,
    ) -> ResourceSnapshot:
        raise NotImplementedError

    def update_task(
        self,
        *,
        task_list_id: str,
        task_id: str,
        payload: dict[str, object],
        claim_context: dict[str, object] | None = None,
    ) -> ResourceSnapshot:
        raise NotImplementedError

    def list_calendars(self, *, page_token: str | None, page_size: int) -> ResourcePage:
        self._maybe_fault("list_calendars")
        self.calls.append(("list_calendars", {"page_token": page_token, "page_size": page_size}))
        return ResourcePage(items=tuple(self.calendars.values())[:page_size], next_page_token=None)

    def list_calendar_events(
        self,
        *,
        calendar_id: str,
        page_token: str | None,
        page_size: int,
        time_min: str | None = None,
        time_max: str | None = None,
        single_events: bool = False,
        order_by: str | None = None,
    ) -> ResourcePage:
        self._maybe_fault("list_calendar_events")
        self.calls.append(
            (
                "list_calendar_events",
                {
                    "calendar_id": calendar_id,
                    "page_token": page_token,
                    "page_size": page_size,
                    "time_min": time_min,
                    "time_max": time_max,
                    "single_events": single_events,
                    "order_by": order_by,
                },
            )
        )
        return ResourcePage(items=tuple(self.events.values())[:page_size], next_page_token=None)

    def query_freebusy(
        self,
        *,
        calendar_ids: tuple[str, ...],
        time_range: TimeRange,
    ) -> tuple[FreeBusyCalendar, ...]:
        self._maybe_fault("query_freebusy")
        self.calls.append(
            (
                "query_freebusy",
                {
                    "calendar_ids": list(calendar_ids),
                    "time_min": time_range.start,
                    "time_max": time_range.end,
                },
            )
        )
        return self.freebusy.get(calendar_ids[0], ())

    def get_calendar_event(self, *, calendar_id: str, event_id: str) -> ResourceSnapshot:
        self._maybe_fault("get_calendar_event")
        self.calls.append(
            ("get_calendar_event", {"calendar_id": calendar_id, "event_id": event_id})
        )
        return self.events[event_id]

    def delete_calendar_event(
        self,
        *,
        calendar_id: str,
        event_id: str,
        claim_context: dict[str, object] | None = None,
    ) -> ResourceSnapshot:
        raise NotImplementedError

    def create_calendar_event(
        self,
        *,
        calendar_id: str,
        payload: dict[str, object],
        claim_context: dict[str, object] | None = None,
    ) -> ResourceSnapshot:
        raise NotImplementedError

    def update_calendar_event(
        self,
        *,
        calendar_id: str,
        event_id: str,
        payload: dict[str, object],
        claim_context: dict[str, object] | None = None,
    ) -> ResourceSnapshot:
        raise NotImplementedError

    def search_by_recovery_fingerprint(
        self,
        *,
        resource_type: ResourceType,
        recovery_fingerprint: str,
    ) -> tuple[ResourceSnapshot, ...]:
        raise NotImplementedError

    def _maybe_fault(self, operation: str) -> None:
        error = self.faults.pop(operation, None)
        if error is not None:
            raise error


@dataclass(frozen=True, slots=True)
class RecordingConnectorReadPort:
    gateway: RecordingGoogleGateway

    def execute_read(
        self,
        binding: ValidatedConnectorToolBindingV1,
        tool_arguments: dict[str, JsonValue],
    ) -> ConnectorReadResultV1:
        arguments = cast(dict[str, object], tool_arguments)
        tool_id = binding.tool_id
        if tool_id == "gmail_search_threads":
            value = self.gateway.search_gmail_threads(
                query=str(arguments["query"]),
                page_token=cast(str | None, arguments.get("page_token")),
                page_size=int(cast(int, arguments["page_size"])),
            )
            output = _page_output(value)
        elif tool_id == "gmail_get_thread":
            output = _item_output(
                self.gateway.get_gmail_thread(thread_id=str(arguments["thread_id"]))
            )
        elif tool_id == "gmail_get_message":
            output = _item_output(
                self.gateway.get_gmail_message(message_id=str(arguments["message_id"]))
            )
        elif tool_id == "gmail_get_draft":
            output = _item_output(self.gateway.get_gmail_draft(draft_id=str(arguments["draft_id"])))
        elif tool_id == "tasks_list_tasklists":
            value = self.gateway.list_task_lists(
                page_token=cast(str | None, arguments.get("page_token")),
                page_size=int(cast(int, arguments["page_size"])),
            )
            output = _page_output(value)
        elif tool_id == "tasks_list_tasks":
            value = self.gateway.list_tasks(
                task_list_id=str(arguments["task_list_id"]),
                page_token=cast(str | None, arguments.get("page_token")),
                page_size=int(cast(int, arguments["page_size"])),
            )
            output = _page_output(value)
        elif tool_id == "tasks_get_task":
            output = _item_output(
                self.gateway.get_task(
                    task_list_id=str(arguments["task_list_id"]),
                    task_id=str(arguments["task_id"]),
                )
            )
        elif tool_id == "calendar_list_calendars":
            value = self.gateway.list_calendars(
                page_token=cast(str | None, arguments.get("page_token")),
                page_size=int(cast(int, arguments["page_size"])),
            )
            output = _page_output(value)
        elif tool_id == "calendar_list_events":
            value = self.gateway.list_calendar_events(
                calendar_id=str(arguments["calendar_id"]),
                page_token=cast(str | None, arguments.get("page_token")),
                page_size=int(cast(int, arguments["page_size"])),
                time_min=cast(str | None, arguments.get("time_min")),
                time_max=cast(str | None, arguments.get("time_max")),
                single_events=bool(arguments.get("single_events", False)),
                order_by=cast(str | None, arguments.get("order_by")),
            )
            output = _page_output(value)
        elif tool_id == "calendar_query_freebusy":
            calendars = self.gateway.query_freebusy(
                calendar_ids=tuple(cast(list[str], arguments["calendar_ids"])),
                time_range=TimeRange(
                    start=str(arguments["time_min"]), end=str(arguments["time_max"])
                ),
            )
            output = {
                "calendars": [
                    {
                        "calendar_id": item.calendar_id,
                        "intervals": [
                            {
                                "start": interval.start,
                                "end": interval.end,
                                "transparency": interval.transparency,
                            }
                            for interval in item.intervals
                        ],
                    }
                    for item in calendars
                ]
            }
        elif tool_id == "calendar_get_event":
            output = _item_output(
                self.gateway.get_calendar_event(
                    calendar_id=str(arguments["calendar_id"]),
                    event_id=str(arguments["event_id"]),
                )
            )
        else:
            raise AssertionError(f"unexpected read tool: {tool_id}")
        return ConnectorReadResultV1(
            schema_version=1,
            tool_id=tool_id,
            request_id="test-request",
            output=cast(dict[str, JsonValue], output),
            next_page_token=cast(str | None, output.get("next_page_token")),
            total_count=None,
        )


def _item_output(snapshot: ResourceSnapshot) -> dict[str, object]:
    return {"item": _snapshot_output(snapshot)}


def _page_output(page: ResourcePage) -> dict[str, object]:
    return {
        "items": [_snapshot_output(item) for item in page.items],
        "next_page_token": page.next_page_token,
    }


def _snapshot_output(snapshot: ResourceSnapshot) -> dict[str, object]:
    return {
        "fixture_snapshot_id": snapshot.fixture_snapshot_id,
        "resource_type": snapshot.resource_type.value,
        "resource_id": snapshot.resource_id,
        "parent_id": snapshot.parent_id,
        "related_resource_ids": list(snapshot.related_resource_ids),
        "version": snapshot.version,
        "recovery_fingerprint": snapshot.recovery_fingerprint,
        "payload": snapshot.payload,
    }


def _connector_reader(gateway: RecordingGoogleGateway) -> ConnectorReadProjection:
    return ConnectorReadProjection(
        connector_reader=RecordingConnectorReadPort(gateway),
        tool_registry=load_signed_tool_registry(),
    )


def test_gmail_single_source_plan_and_acquisition_complete() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result([_plan("GMAIL", {"query": "김대리"})]))
    gateway = RecordingGoogleGateway()
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    assert planning["result"] == ApiPlanningResult.PLAN_READY.value
    assert planning["source_fetch_plans"][0]["source"] == "GMAIL"
    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value
    assert acquisition["resource_handles"] == ["gmail_thread:thread-kim"]
    assert [name for name, _args in gateway.calls] == ["search_gmail_threads", "get_gmail_thread"]


def test_invoke_plan_sources_llm_wires_semantic_validate_to_validate_source_fetch_plans_v1() -> (
    None
):
    """Regression for the D-2-class repair-boundary gap: invoke_plan_sources_llm
    must pass validate_source_fetch_plans_v1 as semantic_validate."""
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result([_plan("GMAIL", {"query": "김대리"})]))
    agent = _agent(runtime=runtime, gateway=RecordingGoogleGateway())

    agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())

    semantic_validate = runtime.calls[0]["semantic_validate"]
    assert semantic_validate is not None
    repaired = cast(
        "list[dict[str, object]]", semantic_validate([_plan("GMAIL", {"query": "김대리"})])
    )
    assert repaired[0]["source"] == "GMAIL"
    with pytest.raises(SourcePlanningValidationError):
        semantic_validate([{"schema_version": 2}])


def test_calendar_single_source_acquisition_complete() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result([_plan("CALENDAR", {"calendar_id": "calendar-primary"})]))
    gateway = RecordingGoogleGateway()
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="CALENDAR"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    assert planning["result"] == ApiPlanningResult.PLAN_READY.value
    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value
    assert [name for name, _args in gateway.calls] == [
        "list_calendar_events",
        "get_calendar_event",
    ]


def test_tasks_single_source_acquisition_complete() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result([_plan("TASKS", {"task_list_id": "task-list-default"})]))
    gateway = RecordingGoogleGateway()
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="TASKS"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    assert planning["result"] == ApiPlanningResult.PLAN_READY.value
    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value
    assert [name for name, _args in gateway.calls] == ["list_tasks", "get_task"]


def test_multi_source_request_acquires_each_planned_source() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            [
                _plan("GMAIL", {"query": "김대리"}, priority=1),
                _plan("CALENDAR", {"calendar_id": "calendar-primary"}, priority=2),
                _plan("TASKS", {"task_list_id": "task-list-default"}, priority=3),
            ]
        )
    )
    gateway = RecordingGoogleGateway()
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    assert planning["result"] == ApiPlanningResult.PLAN_READY.value
    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value
    assert acquisition["resource_handles"] == [
        "gmail_thread:thread-kim",
        "calendar_event:event-1",
        "task:task-1",
    ]


def test_no_fetch_needed_when_planning_returns_empty_plan_list() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result([]))
    gateway = RecordingGoogleGateway()
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())
    state_update = agent.build_planning_state_update(planning)

    assert planning["result"] == ApiPlanningResult.NO_FETCH_NEEDED.value
    assert planning["source_fetch_plans"] == []
    assert state_update["workflow_phase"] == WorkflowPhase.SOURCE_PLANNING.value
    assert "user_interrupt" not in state_update
    assert gateway.calls == []


def test_resource_selected_uses_direct_get_and_does_not_search() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            [
                _plan(
                    "GMAIL",
                    {},
                    reason_codes=["RESOURCE_SELECTED_DIRECT_GET"],
                )
            ]
        )
    )
    gateway = RecordingGoogleGateway()
    agent = _agent(runtime=runtime, gateway=gateway)
    request = _request(
        entry_mode="RESOURCE_SELECTED",
        selected_resource_ids=("thread-kim",),
        selected_resources=(
            SelectedResourceRef(
                source="GMAIL",
                resource_type="THREAD",
                resource_id="thread-kim",
            ),
        ),
    )

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=request)
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=request)

    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value
    assert [name for name, _args in gateway.calls] == ["get_gmail_thread"]
    # retrieval.plan_query's Prompt Runtime Input Contract has no
    # selected_resources/selected_resource_ids/entry_mode field: Tool Route
    # has already frozen input_routes from that same RESOURCE_SELECTED
    # signal, so Retrieval must not re-derive or re-select a route from it.
    assert set(runtime.calls[0]["prompt_input"]) == {
        "request_intent",
        "input_routes",
        "retrieval_budget",
    }
    assert "selected_resource_ids" not in planning["source_fetch_plans"][0]


def test_resource_selected_gmail_thread_expands_to_message_bodies() -> None:
    """GAP-F6: RESOURCE_SELECTED Thread selection must not stop at metadata --
    docs/05 section 7 requires selected-ID detail GET to reach Context the
    same way AGENT_SEARCH candidates do, so the selected Thread's messages
    are expanded through the same Agent Read Port helper (never the
    Sidebar-only UI detail endpoint)."""
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result([_plan("GMAIL", {}, reason_codes=["RESOURCE_SELECTED_DIRECT_GET"])])
    )
    gateway = RecordingGoogleGateway()
    gateway.gmail_threads["thread-kim"].payload["message_ids"] = ["message-1", "message-2"]
    gateway.gmail_messages["message-1"] = _snapshot(
        ResourceType.GMAIL_MESSAGE, "message-1", parent_id="thread-kim", title="첫 메일"
    )
    gateway.gmail_messages["message-2"] = _snapshot(
        ResourceType.GMAIL_MESSAGE, "message-2", parent_id="thread-kim", title="답장"
    )
    agent = _agent(runtime=runtime, gateway=gateway)
    request = _request(
        entry_mode="RESOURCE_SELECTED",
        selected_resource_ids=("thread-kim",),
        selected_resources=(
            SelectedResourceRef(source="GMAIL", resource_type="THREAD", resource_id="thread-kim"),
        ),
    )

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=request)
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=request)

    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value
    assert [name for name, _args in gateway.calls] == [
        "get_gmail_thread",
        "get_gmail_message",
        "get_gmail_message",
    ]
    assert acquisition["resource_handles"] == [
        "gmail_thread:thread-kim",
        "gmail_message:message-1",
        "gmail_message:message-2",
    ]


def test_resource_selected_gmail_thread_is_force_included_when_detail_budget_is_zero() -> None:
    """The selected Thread itself must never be dropped for budget reasons
    (force-include contract); only the follow-on message expansion is
    budget-gated."""
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            [
                _plan(
                    "GMAIL",
                    {},
                    reason_codes=["RESOURCE_SELECTED_DIRECT_GET"],
                    detail_limit=0,
                )
            ]
        )
    )
    gateway = RecordingGoogleGateway()
    gateway.gmail_threads["thread-kim"].payload["message_ids"] = ["message-1"]
    gateway.gmail_messages["message-1"] = _snapshot(
        ResourceType.GMAIL_MESSAGE, "message-1", parent_id="thread-kim", title="첫 메일"
    )
    agent = _agent(
        runtime=runtime,
        gateway=gateway,
        retrieval_budget=RetrievalBudget(max_sources=1, max_details_per_source=0),
    )
    request = _request(
        entry_mode="RESOURCE_SELECTED",
        selected_resource_ids=("thread-kim",),
        selected_resources=(
            SelectedResourceRef(source="GMAIL", resource_type="THREAD", resource_id="thread-kim"),
        ),
    )

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=request)
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=request)

    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value
    assert [name for name, _args in gateway.calls] == ["get_gmail_thread"]
    assert acquisition["resource_handles"] == ["gmail_thread:thread-kim"]


def test_resource_selected_gmail_message_returns_body_directly() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result([_plan("GMAIL", {}, reason_codes=["RESOURCE_SELECTED_DIRECT_GET"])])
    )
    gateway = RecordingGoogleGateway()
    gateway.gmail_messages["message-1"] = _snapshot(
        ResourceType.GMAIL_MESSAGE, "message-1", parent_id="thread-kim", title="첫 메일"
    )
    agent = _agent(runtime=runtime, gateway=gateway)
    request = _request(
        entry_mode="RESOURCE_SELECTED",
        selected_resource_ids=("message-1",),
        selected_resources=(
            SelectedResourceRef(source="GMAIL", resource_type="MESSAGE", resource_id="message-1"),
        ),
    )

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=request)
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=request)

    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value
    assert [name for name, _args in gateway.calls] == ["get_gmail_message"]
    assert acquisition["resource_handles"] == ["gmail_message:message-1"]


def test_resource_selected_uses_task_parent_identity_without_default() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result([_plan("TASKS", {})]))
    gateway = RecordingGoogleGateway()
    agent = _agent(runtime=runtime, gateway=gateway)
    request = _request(
        entry_mode="RESOURCE_SELECTED",
        selected_resources=(
            SelectedResourceRef(
                source="TASKS",
                resource_type="TASK",
                resource_id="task-1",
                parent_resource_id="task-list-default",
            ),
        ),
    )

    planning = agent.plan_sources(request_intent=_intent(source="TASKS"), request=request)
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=request)

    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value
    assert [name for name, _args in gateway.calls] == ["get_task"]
    assert gateway.calls[0][1] == {"task_list_id": "task-list-default", "task_id": "task-1"}


def test_resource_selected_uses_calendar_parent_identity_without_primary() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result([_plan("CALENDAR", {})]))
    gateway = RecordingGoogleGateway()
    agent = _agent(runtime=runtime, gateway=gateway)
    request = _request(
        entry_mode="RESOURCE_SELECTED",
        selected_resources=(
            SelectedResourceRef(
                source="CALENDAR",
                resource_type="EVENT",
                resource_id="event-1",
                parent_resource_id="calendar-primary",
            ),
        ),
    )

    planning = agent.plan_sources(request_intent=_intent(source="CALENDAR"), request=request)
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=request)

    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value
    assert [name for name, _args in gateway.calls] == ["get_calendar_event"]
    assert gateway.calls[0][1] == {"calendar_id": "calendar-primary", "event_id": "event-1"}


def test_resource_selected_missing_parent_identity_fails_without_hidden_default() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result([_plan("TASKS", {})]))
    gateway = RecordingGoogleGateway()
    agent = _agent(runtime=runtime, gateway=gateway)
    request = _request(
        entry_mode="RESOURCE_SELECTED",
        selected_resources=(
            SelectedResourceRef(
                source="TASKS",
                resource_type="TASK",
                resource_id="task-1",
            ),
        ),
    )

    planning = agent.plan_sources(request_intent=_intent(source="TASKS"), request=request)
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=request)

    assert acquisition["status"] == ApiAcquisitionResult.FAILED.value
    assert gateway.calls == []


def test_partial_acquisition_when_one_source_succeeds_and_one_fails() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            [
                _plan("GMAIL", {"query": "김대리"}, priority=1),
                _plan("CALENDAR", {"calendar_id": "calendar-primary"}, priority=2),
            ]
        )
    )
    gateway = RecordingGoogleGateway()
    gateway.queue_fault("list_calendar_events", GoogleWorkspaceErrorCode.UPSTREAM_5XX)
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    assert acquisition["status"] == ApiAcquisitionResult.PARTIAL.value
    assert acquisition["resource_handles"] == ["gmail_thread:thread-kim"]
    assert "CALENDAR:UPSTREAM_5XX" in acquisition["missing_slots"]


def test_validate_acquisition_result_v1_requires_native_result_shape() -> None:
    acquisition = validate_acquisition_result_v1(
        {
            "schema_version": 1,
            "status": "COMPLETE",
            "resource_handles": ["task:task-1"],
            "source_summaries": [
                {
                    "schema_version": 1,
                    "source": "TASKS",
                    "status": "COMPLETE",
                    "required": True,
                    "reason_codes": ["GOAL_RELEVANT"],
                    "resource_count": 1,
                    "resource_handles": ["task:task-1"],
                    "resources": [{"resource_handle": "task:task-1"}],
                }
            ],
            "missing_slots": [],
            "remaining_budget": {
                "sources": 2,
                "pages": 2,
                "candidates": 20,
                "details": 10,
            },
        }
    )

    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value
    assert acquisition["resource_handles"] == ["task:task-1"]


def test_optional_source_failure_with_required_success_returns_partial() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            [
                _plan("GMAIL", {"query": "김대리"}, priority=1),
                _plan(
                    "CALENDAR",
                    {"calendar_id": "calendar-primary"},
                    priority=2,
                    required=False,
                ),
            ]
        )
    )
    gateway = RecordingGoogleGateway()
    gateway.queue_fault("list_calendar_events", GoogleWorkspaceErrorCode.UPSTREAM_5XX)
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    assert acquisition["status"] == ApiAcquisitionResult.PARTIAL.value
    assert acquisition["source_summaries"][1]["required"] is False


def test_required_source_failure_with_optional_success_returns_partial() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            [
                _plan("GMAIL", {"query": "김대리"}, priority=1),
                _plan(
                    "CALENDAR",
                    {"calendar_id": "calendar-primary"},
                    priority=2,
                    required=False,
                ),
            ]
        )
    )
    gateway = RecordingGoogleGateway()
    gateway.queue_fault("search_gmail_threads", GoogleWorkspaceErrorCode.UPSTREAM_5XX)
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    assert acquisition["status"] == ApiAcquisitionResult.PARTIAL.value
    assert acquisition["resource_handles"] == ["calendar_event:event-1"]


def test_auth_required_maps_gateway_auth_failure() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result([_plan("GMAIL", {"query": "김대리"})]))
    gateway = RecordingGoogleGateway()
    gateway.queue_fault("search_gmail_threads", GoogleWorkspaceErrorCode.AUTH_EXPIRED)
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    assert acquisition["status"] == ApiAcquisitionResult.AUTH_REQUIRED.value
    assert acquisition["missing_slots"] == ["GMAIL:AUTH_EXPIRED"]


def test_required_auth_overrides_usable_partial_data() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            [
                _plan("GMAIL", {"query": "김대리"}, priority=1),
                _plan("CALENDAR", {"calendar_id": "calendar-primary"}, priority=2),
            ]
        )
    )
    gateway = RecordingGoogleGateway()
    gateway.queue_fault("list_calendar_events", GoogleWorkspaceErrorCode.AUTH_EXPIRED)
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    assert acquisition["status"] == ApiAcquisitionResult.AUTH_REQUIRED.value
    assert acquisition["resource_handles"] == ["gmail_thread:thread-kim"]


def test_rate_limited_maps_gateway_rate_limit_failure() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result([_plan("GMAIL", {"query": "김대리"})]))
    gateway = RecordingGoogleGateway()
    gateway.queue_fault("search_gmail_threads", GoogleWorkspaceErrorCode.RATE_LIMITED)
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    assert acquisition["status"] == ApiAcquisitionResult.RATE_LIMITED.value
    assert acquisition["missing_slots"] == ["GMAIL:RATE_LIMITED"]


def test_usable_data_with_rate_limit_returns_partial() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            [
                _plan("GMAIL", {"query": "김대리"}, priority=1),
                _plan("CALENDAR", {"calendar_id": "calendar-primary"}, priority=2),
            ]
        )
    )
    gateway = RecordingGoogleGateway()
    gateway.queue_fault("list_calendar_events", GoogleWorkspaceErrorCode.RATE_LIMITED)
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    assert acquisition["status"] == ApiAcquisitionResult.PARTIAL.value
    assert acquisition["resource_handles"] == ["gmail_thread:thread-kim"]


def test_budget_exhausted_when_plan_exceeds_retrieval_budget() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result([_plan("GMAIL", {"query": "김대리"}, page_size=99)]))
    gateway = RecordingGoogleGateway()
    agent = _agent(
        runtime=runtime,
        gateway=gateway,
        retrieval_budget=RetrievalBudget(max_page_size=20),
    )

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    assert acquisition["status"] == ApiAcquisitionResult.BUDGET_EXHAUSTED.value
    assert gateway.calls == []


def test_usable_data_with_budget_exhaustion_returns_partial() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            [
                _plan("GMAIL", {"query": "김대리"}, priority=1),
                _plan("CALENDAR", {"calendar_id": "calendar-primary"}, priority=2, page_size=99),
            ]
        )
    )
    gateway = RecordingGoogleGateway()
    agent = _agent(
        runtime=runtime,
        gateway=gateway,
        retrieval_budget=RetrievalBudget(max_page_size=20),
    )

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    assert acquisition["status"] == ApiAcquisitionResult.PARTIAL.value
    assert acquisition["resource_handles"] == ["gmail_thread:thread-kim"]


def test_no_usable_data_with_mixed_failures_returns_auth_required_first() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            [
                _plan("GMAIL", {"query": "김대리"}, priority=1),
                _plan("CALENDAR", {"calendar_id": "calendar-primary"}, priority=2),
                _plan("TASKS", {"task_list_id": "task-list-default"}, priority=3),
            ]
        )
    )
    gateway = RecordingGoogleGateway()
    gateway.queue_fault("search_gmail_threads", GoogleWorkspaceErrorCode.AUTH_EXPIRED)
    gateway.queue_fault("list_calendar_events", GoogleWorkspaceErrorCode.RATE_LIMITED)
    gateway.queue_fault("list_tasks", GoogleWorkspaceErrorCode.UPSTREAM_5XX)
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    assert acquisition["status"] == ApiAcquisitionResult.AUTH_REQUIRED.value
    assert acquisition["resource_handles"] == []


def test_transport_runtime_failure_maps_to_failed_when_no_source_succeeds() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result([_plan("GMAIL", {"query": "김대리"})]))
    gateway = RecordingGoogleGateway()
    gateway.queue_fault("search_gmail_threads", GoogleWorkspaceErrorCode.UPSTREAM_5XX)
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    assert acquisition["status"] == ApiAcquisitionResult.FAILED.value
    assert acquisition["source_summaries"][0]["error_code"] == "UPSTREAM_5XX"


def test_retrieval_ambiguity_uses_planning_confirmation_not_request_understanding() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            [
                _plan(
                    "CALENDAR",
                    {"person": "민수"},
                    reason_codes=["QUERY_LOW_CONFIDENCE_RESULTS"],
                )
            ]
        )
    )
    gateway = RecordingGoogleGateway()
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="CALENDAR"), request=_request())
    clarification = build_source_planning_clarification_question(
        output=planning,
        request_intent=_intent(source="CALENDAR"),
    )

    assert planning["result"] == ApiPlanningResult.NEEDS_CONFIRMATION.value
    assert planning["clarification"] is not None
    assert clarification["origin_target"] == "acquisition.plan_sources"
    assert clarification["options"] == []
    request_intent = runtime.calls[0]["prompt_input"]["request_intent"]
    assert isinstance(request_intent, dict)
    assert request_intent["schema_version"] == 2
    assert gateway.calls == []


def test_additional_acquisition_request_is_accepted_but_not_leaked_into_plan_query_prompt() -> None:
    """retrieval.plan_query's Prompt Runtime Input Contract has no
    planning_mode/additional_acquisition_request field (additionalProperties:
    false); repeat-round signalling belongs to Retrieval Local State / the
    retrieval.plan_query.revise slot (FOLLOWING_WAVE_DEPENDENCY), not an
    ad-hoc INITIAL-prompt field. The parameter must still be accepted
    without breaking the call -- callers pass it today -- it just must not
    reach the Prompt."""
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result([_plan("GMAIL", {"query": "source follow-up"})]))
    gateway = RecordingGoogleGateway()
    agent = _agent(runtime=runtime, gateway=gateway)
    additional_request: AdditionalAcquisitionRequestV1 = {
        "schema_version": 1,
        "origin_phase": WorkflowPhase.WORK_ANALYSIS.value,
        "origin_result": "NEEDS_MORE_DATA",
        "missing_slots": [],
        "missing_information": ["Need the latest owner reply."],
        "evidence_refs": ["evidence-1"],
        "reason_codes": ["EVIDENCE_SUPPORTED"],
    }

    planning = agent.plan_sources(
        request_intent=_intent(source="GMAIL"),
        request=_request(),
        additional_acquisition_request=additional_request,
    )

    prompt_input = runtime.calls[0]["prompt_input"]
    assert planning["result"] == ApiPlanningResult.PLAN_READY.value
    assert "planning_mode" not in prompt_input
    assert "additional_acquisition_request" not in prompt_input
    assert set(prompt_input) == {
        "request_intent",
        "input_routes",
        "retrieval_budget",
    }


def test_plan_query_projects_frozen_input_routes_without_reselecting_them() -> None:
    """The Prompt only ever sees Tool Route's already-frozen input_routes,
    recoded to the Prompt's coarse EMAIL/TASK/CALENDAR resource_type enum --
    route_id/connector_id/allowed_read_tool_ids/required/reason_codes (the
    actual Registry binding) pass through unchanged, proving Retrieval does
    not reselect a connector/resource/tool."""
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result([_plan("GMAIL", {"query": "kim"})]))
    agent = _agent(runtime=runtime, gateway=RecordingGoogleGateway())
    tool_route_plan: ToolRoutePlanV2 = {
        "schema_version": 2,
        "input_plan": {
            "schema_version": 1,
            "meta": {"artifact_id": "route-1", "revision": 1, "based_on": []},
            "input_routes": [
                {
                    "route_id": "route-0",
                    "resource_type": "GMAIL_THREAD",
                    "connector_id": "google_workspace",
                    "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
                    "required": True,
                    "reason_codes": ["REQUESTED_INPUT"],
                }
            ],
        },
        "output_plan": {
            "schema_version": 1,
            "meta": {"artifact_id": "route-2", "revision": 1, "based_on": []},
            "output_mode": "ANSWER",
        },
        "tool_registry_version": "2026-08-06.p0",
    }

    agent.plan_sources(
        request_intent=_intent(source="GMAIL"),
        request=_request(),
        tool_route_plan=tool_route_plan,
    )

    prompt_input = runtime.calls[0]["prompt_input"]
    assert prompt_input["input_routes"] == [
        {
            "route_id": "route-0",
            "resource_type": "EMAIL",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
            "required": True,
            "reason_codes": ["REQUESTED_INPUT"],
        }
    ]


def test_planning_schema_failure_is_not_google_acquisition_failure() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        LLMInvocationError(
            LLMErrorCode.OUTPUT_SCHEMA_INVALID,
            "structured output did not satisfy schema",
        )
    )
    gateway = RecordingGoogleGateway()
    agent = _agent(runtime=runtime, gateway=gateway)

    try:
        agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())
    except LLMInvocationError as error:
        assert error.code is LLMErrorCode.OUTPUT_SCHEMA_INVALID
    else:
        raise AssertionError("expected schema failure")
    assert gateway.calls == []


def test_source_fetch_plan_rejects_extra_fields() -> None:
    runtime = FakeLLMRuntime()
    plan = dict(_plan("GMAIL", {"query": "김대리"}))
    plan["query"] = "from:kim"
    runtime.queued.append(_llm_result([plan]))
    gateway = RecordingGoogleGateway()
    agent = _agent(runtime=runtime, gateway=gateway)

    try:
        agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())
    except SourcePlanningValidationError as error:
        assert "unsupported fields" in str(error)
    else:
        raise AssertionError("expected source plan validation failure")
    assert gateway.calls == []


def test_acquisition_result_has_stage5_handoff_fields() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result([_plan("GMAIL", {"query": "김대리"})]))
    gateway = RecordingGoogleGateway()
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    assert set(acquisition) == {
        "schema_version",
        "status",
        "resource_handles",
        "source_summaries",
        "missing_slots",
        "remaining_budget",
    }
    assert set(acquisition["source_summaries"][0]) == {
        "schema_version",
        "source",
        "status",
        "required",
        "reason_codes",
        "resource_count",
        "resource_handles",
        "resources",
    }


def test_planning_agent_does_not_call_google_or_mcp() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result([_plan("GMAIL", {"query": "김대리"})]))
    gateway = RecordingGoogleGateway()
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())

    assert planning["result"] == ApiPlanningResult.PLAN_READY.value
    assert len(runtime.calls) == 1
    assert gateway.calls == []


def test_acquisition_payload_does_not_include_stage6_outputs() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result([_plan("GMAIL", {"query": "김대리"})]))
    gateway = RecordingGoogleGateway()
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())
    state_update = agent.build_acquisition_state_update(acquisition)

    assert state_update["acquisition_result"] == acquisition
    assert state_update["workflow_phase"] == WorkflowPhase.API_ACQUISITION.value
    for forbidden in ("context_bundle", "evidence_drafts", "analysis_result", "plan_draft"):
        assert forbidden not in acquisition
    assert "score" not in acquisition["source_summaries"][0]


def test_gmail_thread_messages_are_fetched_for_body_text() -> None:
    """GAP-F6: candidate narrowing (search -> detail_limit threads) already
    existed; this locks in the missing second hop -- each detail-fetched
    thread's messages are read too, in thread order, so Evidence gets real
    body text instead of only thread-level subject/snippet."""
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result([_plan("GMAIL", {"query": "김대리"})]))
    gateway = RecordingGoogleGateway()
    gateway.gmail_threads["thread-kim"].payload["message_ids"] = ["message-1", "message-2"]
    gateway.gmail_messages["message-1"] = _snapshot(
        ResourceType.GMAIL_MESSAGE,
        "message-1",
        parent_id="thread-kim",
        title="첫 메일",
    )
    gateway.gmail_messages["message-2"] = _snapshot(
        ResourceType.GMAIL_MESSAGE,
        "message-2",
        parent_id="thread-kim",
        title="답장",
    )
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value
    assert [name for name, _args in gateway.calls] == [
        "search_gmail_threads",
        "get_gmail_thread",
        "get_gmail_message",
        "get_gmail_message",
    ]
    assert acquisition["resource_handles"] == [
        "gmail_thread:thread-kim",
        "gmail_message:message-1",
        "gmail_message:message-2",
    ]


def test_gmail_thread_with_no_messages_does_not_call_get_gmail_message() -> None:
    """A thread whose metadata carries no message_ids (e.g. thread-finance in
    the product fixtures) must not attempt a message detail GET."""
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result([_plan("GMAIL", {"query": "김대리"})]))
    gateway = RecordingGoogleGateway()
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value
    assert [name for name, _args in gateway.calls] == ["search_gmail_threads", "get_gmail_thread"]


def test_gmail_message_fetch_failure_does_not_abort_the_thread() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result([_plan("GMAIL", {"query": "김대리"})]))
    gateway = RecordingGoogleGateway()
    gateway.gmail_threads["thread-kim"].payload["message_ids"] = ["message-1", "message-2"]
    gateway.gmail_messages["message-1"] = _snapshot(
        ResourceType.GMAIL_MESSAGE, "message-1", parent_id="thread-kim", title="첫 메일"
    )
    gateway.gmail_messages["message-2"] = _snapshot(
        ResourceType.GMAIL_MESSAGE, "message-2", parent_id="thread-kim", title="답장"
    )
    gateway.queue_fault("get_gmail_message", GoogleWorkspaceErrorCode.NOT_FOUND)
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value
    assert acquisition["resource_handles"] == [
        "gmail_thread:thread-kim",
        "gmail_message:message-2",
    ]


def test_gmail_message_fetch_stops_when_detail_budget_is_exhausted() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(_llm_result([_plan("GMAIL", {"query": "김대리"}, detail_limit=2)]))
    gateway = RecordingGoogleGateway()
    gateway.gmail_threads["thread-kim"].payload["message_ids"] = ["message-1", "message-2"]
    gateway.gmail_messages["message-1"] = _snapshot(
        ResourceType.GMAIL_MESSAGE, "message-1", parent_id="thread-kim", title="첫 메일"
    )
    gateway.gmail_messages["message-2"] = _snapshot(
        ResourceType.GMAIL_MESSAGE, "message-2", parent_id="thread-kim", title="답장"
    )
    # 1 source * 2 details = a total budget of 2 detail-fetches: the thread
    # itself plus exactly one message, leaving the second message unfetched.
    agent = _agent(
        runtime=runtime,
        gateway=gateway,
        retrieval_budget=RetrievalBudget(max_sources=1, max_details_per_source=2),
    )

    planning = agent.plan_sources(request_intent=_intent(source="GMAIL"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    assert [name for name, _args in gateway.calls] == [
        "search_gmail_threads",
        "get_gmail_thread",
        "get_gmail_message",
    ]
    assert acquisition["resource_handles"] == [
        "gmail_thread:thread-kim",
        "gmail_message:message-1",
    ]


# GAP-F7 Runtime test matrix (A-H). Each scenario is named after the
# completion report's lettered requirement so the mapping stays traceable.


def test_scenario_a_simple_listing_is_events_only_and_skips_freebusy() -> None:
    """A: "내일 일정 알려줘" -> typed EVENTS_ONLY -> FreeBusy 0."""
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            [
                _plan(
                    "CALENDAR",
                    {"calendar_id": "calendar-primary"},
                    calendar_read_mode="EVENTS_ONLY",
                    temporal_query=_temporal_query(relative_unit="DAY", relative_offset=1),
                )
            ]
        )
    )
    gateway = RecordingGoogleGateway()
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="CALENDAR"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    call_names = [name for name, _args in gateway.calls]
    assert "query_freebusy" not in call_names
    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value


def test_scenario_b_tomorrow_afternoon_resolves_range_and_calls_freebusy_once() -> None:
    """B: "내일 오후에 가능한 시간 찾아줘" -> EVENTS_AND_FREEBUSY, DAY+1, AFTERNOON
    -> deterministic TimeRange in Asia/Seoul -> FreeBusy 1."""
    now_ms = _epoch_ms("2026-08-11T10:00:00+09:00")  # Tuesday
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            [
                _plan(
                    "CALENDAR",
                    {"calendar_id": "calendar-primary"},
                    calendar_read_mode="EVENTS_AND_FREEBUSY",
                    temporal_query=_temporal_query(
                        relative_unit="DAY",
                        relative_offset=1,
                        daypart="AFTERNOON",
                    ),
                )
            ]
        )
    )
    gateway = RecordingGoogleGateway()
    gateway.freebusy["calendar-primary"] = ()
    agent = _agent(runtime=runtime, gateway=gateway, now_ms=now_ms, timezone="Asia/Seoul")

    planning = agent.plan_sources(request_intent=_intent(source="CALENDAR"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    freebusy_calls = [args for name, args in gateway.calls if name == "query_freebusy"]
    assert len(freebusy_calls) == 1
    assert freebusy_calls[0]["time_min"] == "2026-08-12T12:00:00+09:00"
    assert freebusy_calls[0]["time_max"] == "2026-08-12T18:00:00+09:00"
    assert any(
        handle.startswith("calendar_freebusy:") for handle in acquisition["resource_handles"]
    )


def test_scenario_c_this_week_availability_spans_the_full_local_week() -> None:
    """C: "이번 주에 빈 시간 찾아줘" -> EVENTS_AND_FREEBUSY, WEEK+0 -> current
    timezone week range -> FreeBusy 1."""
    now_ms = _epoch_ms("2026-08-11T10:00:00+09:00")
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            [
                _plan(
                    "CALENDAR",
                    {"calendar_id": "calendar-primary"},
                    calendar_read_mode="EVENTS_AND_FREEBUSY",
                    temporal_query=_temporal_query(relative_unit="WEEK", relative_offset=0),
                )
            ]
        )
    )
    gateway = RecordingGoogleGateway()
    gateway.freebusy["calendar-primary"] = ()
    agent = _agent(runtime=runtime, gateway=gateway, now_ms=now_ms, timezone="Asia/Seoul")

    planning = agent.plan_sources(request_intent=_intent(source="CALENDAR"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    freebusy_calls = [args for name, args in gateway.calls if name == "query_freebusy"]
    assert len(freebusy_calls) == 1
    start = datetime.fromisoformat(str(freebusy_calls[0]["time_min"]))
    end = datetime.fromisoformat(str(freebusy_calls[0]["time_max"]))
    assert start.weekday() == 0  # Monday-anchored week
    assert (end - start) == timedelta(days=7)
    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value


def test_scenario_d_friday_listing_is_events_only_and_skips_freebusy() -> None:
    """D: "금요일 일정 알려줘" -> EVENTS_ONLY -> FreeBusy 0."""
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            [
                _plan(
                    "CALENDAR",
                    {"calendar_id": "calendar-primary"},
                    calendar_read_mode="EVENTS_ONLY",
                    temporal_query=_temporal_query(
                        relative_unit="WEEK", relative_offset=0, weekday="FRI"
                    ),
                )
            ]
        )
    )
    gateway = RecordingGoogleGateway()
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="CALENDAR"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    call_names = [name for name, _args in gateway.calls]
    assert "query_freebusy" not in call_names
    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value


def test_scenario_e_availability_keyword_in_text_does_not_override_typed_events_only() -> None:
    """E (keyword trap): request text says "available" but the typed plan is
    EVENTS_ONLY -> FreeBusy 0. Confirms the gate reads only the typed field,
    never request text."""
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            [
                _plan(
                    "CALENDAR",
                    {"calendar_id": "calendar-primary"},
                    calendar_read_mode="EVENTS_ONLY",
                )
            ]
        )
    )
    gateway = RecordingGoogleGateway()
    agent = _agent(runtime=runtime, gateway=gateway)
    request = _request(request_text="Is Kim available tomorrow? Just list events.")

    planning = agent.plan_sources(request_intent=_intent(source="CALENDAR"), request=request)
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=request)

    call_names = [name for name, _args in gateway.calls]
    assert "query_freebusy" not in call_names
    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value


def test_scenario_f_no_availability_wording_still_calls_freebusy_when_typed_mode_requires_it() -> (
    None
):
    """F (reverse trap): request text has no availability wording, but the
    typed plan is EVENTS_AND_FREEBUSY -> FreeBusy 1 anyway."""
    now_ms = _epoch_ms("2026-08-11T10:00:00+09:00")
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            [
                _plan(
                    "CALENDAR",
                    {"calendar_id": "calendar-primary"},
                    calendar_read_mode="EVENTS_AND_FREEBUSY",
                    temporal_query=_temporal_query(relative_unit="DAY", relative_offset=0),
                )
            ]
        )
    )
    gateway = RecordingGoogleGateway()
    gateway.freebusy["calendar-primary"] = ()
    agent = _agent(runtime=runtime, gateway=gateway, now_ms=now_ms)
    request = _request(request_text="회의 목록 좀 줘.")

    planning = agent.plan_sources(request_intent=_intent(source="CALENDAR"), request=request)
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=request)

    call_names = [name for name, _args in gateway.calls]
    assert call_names.count("query_freebusy") == 1
    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value


def test_scenario_g_invalid_temporal_proposal_skips_google_and_flags_deterministically() -> None:
    """G: a structurally valid but semantically invalid temporal_query
    (ABSOLUTE end before start) -> Google FreeBusy call 0, and a
    deterministic failure signal surfaces in missing_slots instead of a
    silent no-op."""
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            [
                _plan(
                    "CALENDAR",
                    {"calendar_id": "calendar-primary"},
                    calendar_read_mode="EVENTS_AND_FREEBUSY",
                    temporal_query=_temporal_query(
                        relation="ABSOLUTE",
                        absolute_start="2026-08-13T00:00:00-07:00",
                        absolute_end="2026-08-12T00:00:00-07:00",
                    ),
                )
            ]
        )
    )
    gateway = RecordingGoogleGateway()
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="CALENDAR"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    call_names = [name for name, _args in gateway.calls]
    assert "query_freebusy" not in call_names
    assert "CALENDAR:INVALID_TEMPORAL_QUERY" in acquisition["missing_slots"]
    assert acquisition["source_summaries"][0]["status"] == ApiAcquisitionResult.COMPLETE.value


def test_scenario_h_seoul_timezone_date_boundary() -> None:
    """H: a request just after local midnight in Asia/Seoul must resolve
    "tomorrow" using the Seoul calendar day, not a UTC day boundary."""
    # 2026-08-12T00:30:00+09:00 is still 2026-08-11T15:30:00Z -- if the
    # resolver used UTC dates instead of the configured timezone, "tomorrow"
    # would land on the wrong day.
    now_ms = _epoch_ms("2026-08-12T00:30:00+09:00")
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            [
                _plan(
                    "CALENDAR",
                    {"calendar_id": "calendar-primary"},
                    calendar_read_mode="EVENTS_AND_FREEBUSY",
                    temporal_query=_temporal_query(relative_unit="DAY", relative_offset=1),
                )
            ]
        )
    )
    gateway = RecordingGoogleGateway()
    gateway.freebusy["calendar-primary"] = ()
    agent = _agent(runtime=runtime, gateway=gateway, now_ms=now_ms, timezone="Asia/Seoul")

    planning = agent.plan_sources(request_intent=_intent(source="CALENDAR"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    freebusy_calls = [args for name, args in gateway.calls if name == "query_freebusy"]
    assert len(freebusy_calls) == 1
    assert str(freebusy_calls[0]["time_min"]).startswith("2026-08-13T00:00:00")
    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value


def test_temporal_query_resolution_handles_dst_timezone_without_error() -> None:
    """DST sanity check: a WEEK-relative query in a DST-observing timezone
    (America/New_York) must still resolve to a valid, well-formed TimeRange
    -- ZoneInfo arithmetic itself must not error or silently misalign
    across a DST transition."""
    from google_work_agent.application.orchestration.api_acquisition import _resolve_temporal_query

    # 2026-03-08 is the US DST spring-forward date; a WEEK query anchored a
    # few days before it exercises ZoneInfo across the transition.
    now_ms = _epoch_ms("2026-03-05T10:00:00-05:00")
    query = _temporal_query(relative_unit="WEEK", relative_offset=0)

    time_range = _resolve_temporal_query(
        temporal_query=query, now_ms=now_ms, timezone="America/New_York"
    )

    assert time_range is not None
    start = datetime.fromisoformat(time_range.start)
    end = datetime.fromisoformat(time_range.end)
    assert start.weekday() == 0
    assert end > start


def test_calendar_freebusy_skipped_when_calendar_cannot_be_resolved() -> None:
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result(
            [
                _plan(
                    "CALENDAR",
                    {},
                    calendar_read_mode="EVENTS_AND_FREEBUSY",
                    temporal_query=_temporal_query(relative_unit="DAY", relative_offset=1),
                )
            ]
        )
    )
    gateway = RecordingGoogleGateway()
    gateway.calendars = {}
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="CALENDAR"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    call_names = [name for name, _args in gateway.calls]
    assert call_names == ["list_calendars"]
    assert "query_freebusy" not in call_names
    assert acquisition["resource_handles"] == []


def test_gap_acq_status_required_source_with_zero_resources_still_reports_complete() -> None:
    """Pins a pre-existing (not F4/F6/F7-introduced) Acquisition contract gap
    surfaced while testing GAP-F7's "missing required Calendar" path: when a
    required source resolves to zero resources without raising (calendar_id
    cannot be determined, or a search legitimately finds nothing), the
    per-source and overall AcquisitionResult.status is unconditionally
    COMPLETE -- indistinguishable from "required data legitimately absent"
    vs. "search found nothing," and from "we can determine calendar_id but
    it's simply empty" vs. "we could not even identify which calendar to
    read." This test intentionally documents current behavior (it does NOT
    assert this is correct) -- see the GAP-F4/F6/F7 completion report for
    why no code change was made here: Acquisition COMPLETE appears to encode
    "the Read finished without a transport error," while insufficient-data
    escalation is a downstream Context Retrieval sufficiency judgement
    (docs/05 section 18.2), and changing this status semantic would affect
    every source (Gmail/Tasks too), which is out of this Retrieval slice's
    scope."""
    runtime = FakeLLMRuntime()
    runtime.queued.append(
        _llm_result([_plan("CALENDAR", {}, reason_codes=["SOURCE_REQUIRED"], required=True)])
    )
    gateway = RecordingGoogleGateway()
    gateway.calendars = {}
    agent = _agent(runtime=runtime, gateway=gateway)

    planning = agent.plan_sources(request_intent=_intent(source="CALENDAR"), request=_request())
    acquisition = agent.acquire(plans=planning["source_fetch_plans"], request=_request())

    assert planning["source_fetch_plans"][0]["required"] is True
    assert acquisition["resource_handles"] == []
    assert acquisition["source_summaries"][0]["resource_count"] == 0
    assert acquisition["source_summaries"][0]["status"] == ApiAcquisitionResult.COMPLETE.value
    assert acquisition["status"] == ApiAcquisitionResult.COMPLETE.value
    assert acquisition["missing_slots"] == []


def _agent(
    *,
    runtime: FakeLLMRuntime,
    gateway: RecordingGoogleGateway,
    retrieval_budget: RetrievalBudget = DEFAULT_TEST_RETRIEVAL_BUDGET,
    now_ms: int | None = None,
    timezone: str = "Asia/Seoul",
) -> ApiDiscoveryAcquisitionAgent:
    return ApiDiscoveryAcquisitionAgent(
        llm_runtime=runtime,
        connector_reader=_connector_reader(gateway),
        prompt_ref=PROMPT_REF,
        retrieval_budget=retrieval_budget,
        now_ms=(lambda: now_ms) if now_ms is not None else None,
        timezone_provider=lambda: timezone,
    )


def _request(
    *,
    entry_mode: str = "AGENT_SEARCH",
    selected_resource_ids: tuple[str, ...] = (),
    selected_resources: tuple[SelectedResourceRef, ...] = (),
    request_text: str = "김대리 메일 찾아줘.",
) -> WorkflowStartRequest:
    return WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode=entry_mode,
        requested_mode="AUTO",
        request_text=request_text,
        selected_resource_ids=selected_resource_ids,
        correlation=WorkflowCorrelationContext(
            request_id="request-1",
            command_id="command-1",
            api_contract_version="v1",
        ),
        selected_resources=selected_resources,
    )


def _intent(*, source: SourceName) -> RequestIntentV2:
    return {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "Google Workspace 자료 조회",
        "completion_conditions": ["필요한 원본 자료를 수집한다."],
        "constraints": [
            {"kind": "PERSON", "field": "person", "value": "김대리"},
            {"kind": "TIME", "field": "time_range", "value": "이번 주"},
        ],
        "ambiguity": {
            "requires_confirmation": False,
            "reason_codes": [],
            "missing_fields": [],
        },
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": [source],
        "analysis_requirement": "REQUIRED",
    }


def _plan(
    source: SourceName,
    constraints: dict[str, object],
    *,
    priority: int = 1,
    reason_codes: list[str] | None = None,
    page_size: int = 10,
    required: bool = True,
    detail_limit: int = 5,
    calendar_read_mode: CalendarReadMode | None = None,
    temporal_query: TemporalQueryV1 | None = None,
) -> SourceFetchPlanV1:
    # CALENDAR plans must carry a non-null calendar_read_mode; tests that
    # don't care about FreeBusy gating get a harmless EVENTS_ONLY default so
    # they don't all need to spell it out.
    resolved_read_mode = calendar_read_mode
    if source == "CALENDAR" and resolved_read_mode is None:
        resolved_read_mode = "EVENTS_ONLY"
    return {
        "schema_version": 2,
        "source": source,
        "priority": priority,
        "reason_codes": reason_codes or ["SOURCE_REQUIRED"],
        "constraints": constraints,
        "page_size": page_size,
        "max_pages": 1,
        "max_candidates": 10,
        "detail_limit": detail_limit,
        "required": required,
        "calendar_read_mode": resolved_read_mode,
        "temporal_query": temporal_query,
    }


def _temporal_query(
    *,
    relation: TemporalRelation = "RELATIVE",
    relative_unit: RelativeUnit | None = None,
    relative_offset: int | None = None,
    weekday: Weekday | None = None,
    daypart: Daypart | None = None,
    absolute_start: str | None = None,
    absolute_end: str | None = None,
) -> TemporalQueryV1:
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


def _epoch_ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


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


def _snapshot(
    resource_type: ResourceType,
    resource_id: str,
    *,
    parent_id: str | None = None,
    title: str,
    subject: str | None = None,
) -> ResourceSnapshot:
    payload: dict[str, object] = {"title": title}
    if subject is not None:
        payload["subject"] = subject
    return ResourceSnapshot(
        fixture_snapshot_id="fixture-1",
        resource_type=resource_type,
        resource_id=resource_id,
        parent_id=parent_id,
        related_resource_ids=(),
        version="1",
        recovery_fingerprint=None,
        payload=payload,
    )
