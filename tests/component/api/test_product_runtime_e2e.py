from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient
from tests.integration.langgraph.test_runtime import (
    _action_required_intent,
    _analysis_output,
    _calendar_analysis_output,
    _calendar_intent,
    _calendar_selection_output,
    _delete_write_plan_output,
    _make_runtime,
    _review_output,
    _runtime_active_manifest_path,
    _selection_output,
    _send_write_plan_output,
    _sufficiency_output,
    _write_plan_output,
)
from tests.support.fakes import DeterministicUUID, FakeClock, FakeGoogleGateway
from tests.support.fixtures import ProductFixtureSnapshotLoader
from tests.unit.application.workflows.test_api_acquisition import _plan

from google_work_agent.adapters.events.in_memory import InMemoryRunEventPublisher
from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.adapters.readiness.composite import (
    StaticReadinessAggregator,
    StaticRuntimeStatusProvider,
)
from google_work_agent.api import ApiContainer, create_app
from google_work_agent.application.coordinator import LocalRunCoordinator
from google_work_agent.application.queries import QueryService
from google_work_agent.application.start_run import (
    CreateConversationService,
    ModifyWriteActionService,
    RejectWriteActionService,
    ResumeRunService,
    StartRunService,
)
from google_work_agent.application.workflows import ActionPlanDraftV1
from google_work_agent.application.write_actions import (
    ApproveWriteActionService,
    PrepareWriteRetryService,
    RequestRunCancellationService,
)
from google_work_agent.ports import (
    AccessDecision,
    ApiRequestContext,
    EndpointPolicy,
    ReadinessCheckResult,
    ReadinessReport,
    ReadinessState,
    RuntimeSummary,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "product"


class _AllowGuard:
    def authorize(
        self,
        request_context: ApiRequestContext,
        *,
        endpoint_policy: EndpointPolicy,
    ) -> AccessDecision:
        del request_context, endpoint_policy
        return AccessDecision(allowed=True)


def _gmail_draft_plan() -> ActionPlanDraftV1:
    plan = _write_plan_output()
    payload = {
        "resource_id": "draft-product-e2e",
        "to": ["pm@example.com"],
        "subject": "Product E2E draft",
        "body": "Deterministic product integration draft.",
    }
    plan["actions"][0].update(
        {
            "effect": "CREATE",
            "tool_name": "gmail_create_draft",
            "arguments": {"payload": payload},
            "expected": {
                "resource_type": "gmail_draft",
                "resource_id": "draft-product-e2e",
                "parent_id": None,
                "version": "1",
                "payload": payload,
            },
        }
    )
    return plan


def _task_update_plan() -> ActionPlanDraftV1:
    plan = _write_plan_output()
    payload = {
        "title": "Reply to project sync",
        "notes": "Reference the Thursday summary.",
        "due": "2026-08-07",
        "status": "completed",
    }
    plan["actions"][0].update(
        {
            "effect": "UPDATE",
            "tool_name": "tasks_update_task",
            "arguments": {
                "task_list_id": "task-list-default",
                "task_id": "task-followup",
                "payload": {"status": "completed"},
            },
            "expected": {
                "resource_type": "task",
                "resource_id": "task-followup",
                "parent_id": "task-list-default",
                "version": "5",
                "payload": payload,
            },
            "target_resource_ref_id": "task:task-followup",
        }
    )
    return plan


def _calendar_create_plan() -> ActionPlanDraftV1:
    plan = _write_plan_output()
    payload = {
        "resource_id": "event-product-e2e",
        "title": "Product E2E event",
        "status": "confirmed",
        "start": "2026-11-02T09:00:00-08:00",
        "end": "2026-11-02T09:30:00-08:00",
    }
    plan["actions"][0].update(
        {
            "effect": "CREATE",
            "tool_name": "calendar_create_event",
            "arguments": {"calendar_id": "calendar-primary", "payload": payload},
            "expected": {
                "resource_type": "calendar_event",
                "resource_id": "event-product-e2e",
                "parent_id": "calendar-primary",
                "version": "1",
                "payload": payload,
            },
            "target_resource_ref_id": None,
        }
    )
    return plan


def _calendar_update_plan() -> ActionPlanDraftV1:
    plan = _delete_write_plan_output()
    payload = {
        "title": "Updated focus block",
        "status": "confirmed",
        "transparency": "busy",
        "event_kind": "focusTime",
        "start": "2026-11-01T08:00:00-07:00",
        "end": "2026-11-01T09:00:00-07:00",
    }
    plan["actions"][0].update(
        {
            "effect": "UPDATE",
            "tool_name": "calendar_update_event",
            "arguments": {
                "calendar_id": "calendar-primary",
                "event_id": "event-focus",
                "payload": {"title": "Updated focus block"},
            },
            "expected": {
                "resource_type": "calendar_event",
                "resource_id": "event-focus",
                "parent_id": "calendar-primary",
                "version": "8",
                "payload": payload,
            },
        }
    )
    return plan


def _task_delete_plan() -> ActionPlanDraftV1:
    plan = _write_plan_output()
    plan["actions"][0].update(
        {
            "effect": "DELETE",
            "tool_name": "tasks_delete_task",
            "arguments": {"task_list_id": "task-list-default", "task_id": "task-followup"},
            "expected": {
                "resource_type": "task",
                "resource_id": "task-followup",
                "absent": True,
            },
            "target_resource_ref_id": "task:task-followup",
        }
    )
    return plan


@pytest.mark.parametrize(
    ("plan_factory", "calendar_context", "write_operation", "verification_operation"),
    [
        (_gmail_draft_plan, False, "create_gmail_draft", "get_gmail_draft"),
        (_send_write_plan_output, False, "send_gmail", "get_gmail_message"),
        (_write_plan_output, False, "create_task", "get_task"),
        (_task_update_plan, False, "update_task", "get_task"),
        (_task_delete_plan, False, "delete_task", "get_task"),
        (_calendar_create_plan, False, "create_calendar_event", "get_calendar_event"),
        (_calendar_update_plan, True, "update_calendar_event", "get_calendar_event"),
        (_delete_write_plan_output, True, "delete_calendar_event", "get_calendar_event"),
    ],
)
def test_product_api_approval_resumes_langgraph_and_verifies_one_google_write(
    tmp_path: Path,
    plan_factory: Callable[[], ActionPlanDraftV1],
    calendar_context: bool,
    write_operation: str,
    verification_operation: str,
) -> None:
    database_path = _seed_product_database(tmp_path)
    clock = FakeClock(1000)
    unit_of_work_factory = sqlite_unit_of_work_factory(database_path)
    gateway = FakeGoogleGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    llm_payloads = (
        [
            _calendar_intent(),
            [_plan("CALENDAR", {"calendar_id": "calendar-primary"})],
            _calendar_selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _calendar_analysis_output(),
            plan_factory(),
            _review_output("PASS"),
        ]
        if calendar_context
        else [
            _action_required_intent(),
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            plan_factory(),
            _review_output("PASS"),
        ]
    )
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=llm_payloads,
        gateway=gateway,
        checkpoint_database_path=tmp_path / "product-checkpoints.db",
        prompt_manifest_path=_runtime_active_manifest_path(tmp_path),
    )
    status_provider = StaticRuntimeStatusProvider(
        RuntimeSummary(
            google="CONNECTED",
            mcp="READY",
            api_llm="AVAILABLE",
            ollama="NOT_AVAILABLE",
            deployment_profile="test",
            recovery_required_run_ids=(),
            open_run_ids=(),
        )
    )
    query_service = QueryService(
        database_path=database_path,
        runtime_status_provider=status_provider,
    )
    publisher = InMemoryRunEventPublisher(service_instance_id="svc-product", capacity_per_run=32)
    coordinator = LocalRunCoordinator(
        query_service=query_service,
        unit_of_work_factory=unit_of_work_factory,
        workflow_runtime=runtime,
        event_publisher=publisher,
        now_ms=clock.now_ms,
        api_contract_version="1",
        capacity=8,
    )
    container = ApiContainer(
        unit_of_work_factory=unit_of_work_factory,
        query_service=query_service,
        create_conversation_service=CreateConversationService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        start_run_service=StartRunService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        approve_action_service=ApproveWriteActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        modify_action_service=ModifyWriteActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
            gateway=gateway,
        ),
        reject_action_service=RejectWriteActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        prepare_retry_service=PrepareWriteRetryService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        cancel_run_service=RequestRunCancellationService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        resume_run_service=ResumeRunService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        local_run_coordinator=coordinator,
        workflow_runtime=runtime,
        event_publisher=publisher,
        readiness_aggregator=StaticReadinessAggregator(
            ReadinessReport(
                state=ReadinessState.READY,
                checks=(ReadinessCheckResult(name="sqlite", state=ReadinessState.READY),),
            )
        ),
        runtime_status_provider=status_provider,
        api_access_guard=_AllowGuard(),
        clock=clock,
        id_generator=DeterministicUUID(prefix="api"),
        release_version="test",
        environment="test",
        service_instance_id="svc-product",
        local_bind_host="127.0.0.1",
        local_bind_port=8780,
        client_address_resolver=lambda _request: "127.0.0.1",
    )

    with TestClient(create_app(container), base_url="http://127.0.0.1:8780") as client:
        _create_conversation_and_run(client)
        waiting = _wait_for_snapshot(client, "WAITING_APPROVAL")
        action = _first_action(waiting)
        reads_before_approval = gateway.count_calls(verification_operation)

        approval_body = {
            "command_id": "approve-command-1",
            "expected_version": action["version"],
            "ttl_ms": 30_000,
            "api_contract_version": "1",
        }
        approved = client.post("/api/v1/actions/action-1/approve", json=approval_body)
        assert approved.status_code == 200
        completed = _wait_for_snapshot(client, "COMPLETED")

        assert _first_action(completed)["status"] == "VERIFIED"
        assert gateway.count_calls(write_operation) == 1
        assert gateway.count_calls(verification_operation) >= reads_before_approval + 1
        replay = client.post("/api/v1/actions/action-1/approve", json=approval_body)
        assert replay.status_code == 200
        conflict = client.post(
            "/api/v1/actions/action-1/approve",
            json={**approval_body, "ttl_ms": 60_000},
        )
        assert conflict.status_code == 409
        time.sleep(0.05)
        assert gateway.count_calls(write_operation) == 1

    connection = connect_sqlite(database_path)
    try:
        counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM approvals),
                (SELECT COUNT(*) FROM execution_attempts),
                (SELECT COUNT(*) FROM verifications),
                (SELECT COUNT(*) FROM audit_events WHERE action_id = 'action-1'),
                (SELECT COUNT(*) FROM trace_events WHERE action_id = 'action-1');
            """
        ).fetchone()
        expected_audit_count = 6 if write_operation == "create_task" else 4
        assert tuple(counts) == (1, 1, 1, expected_audit_count, 4)
    finally:
        connection.close()

    event_types = [
        event.event_type for event in publisher.replay(run_id="run-1", after_event_id=None)
    ]
    assert "approval_required" in event_types
    assert "completed" in event_types


def _seed_product_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "product-e2e.db"
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            """
            INSERT INTO google_accounts (id, email, display_name, connected_at_ms)
            VALUES ('account-1', 'user@example.com', 'User', 1);
            """
        )
    finally:
        connection.close()
    return database_path


def _create_conversation_and_run(client: TestClient) -> None:
    conversation = client.post(
        "/api/v1/conversations",
        json={
            "command_id": "conversation-command-1",
            "conversation_id": "conversation-1",
            "account_id": "account-1",
            "title": "Product E2E",
            "api_contract_version": "1",
        },
    )
    assert conversation.status_code == 201
    started = client.post(
        "/api/v1/runs",
        json={
            "command_id": "run-command-1",
            "conversation_id": "conversation-1",
            "user_message_id": "message-1",
            "run_id": "run-1",
            "workflow_key": "workflow-1",
            "request_text": "Create the requested follow-up task.",
            "entry_mode": "AGENT_SEARCH",
            "selected_resource_ids": [],
            "selected_resources": [],
            "requested_mode": "AUTO",
            "api_contract_version": "1",
        },
    )
    assert started.status_code == 202


def _wait_for_snapshot(client: TestClient, expected_status: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    latest: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = client.get("/api/v1/runs/run-1")
        assert response.status_code == 200
        latest = response.json()["snapshot"]
        if latest["status"] == expected_status:
            return latest
        time.sleep(0.01)
    raise AssertionError(f"run did not reach {expected_status}: {latest}")


def _first_action(snapshot: dict[str, object]) -> dict[str, object]:
    actions = snapshot.get("actions")
    if not isinstance(actions, list) or not actions or not isinstance(actions[0], dict):
        raise AssertionError("run snapshot must contain at least one action object")
    action = actions[0]
    if not all(isinstance(key, str) for key in action):
        raise AssertionError("action keys must be strings")
    return cast(dict[str, object], action)
