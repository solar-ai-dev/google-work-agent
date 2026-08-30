from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal, cast

import pytest
from fastapi.testclient import TestClient
from tests.integration.langgraph.test_runtime import (
    _action_intent,
    _analysis_output,
    _calendar_analysis_output,
    _calendar_selection_output,
    _delete_write_plan_output,
    _gmail_analysis_output,
    _gmail_selection_output,
    _make_runtime,
    _review_output,
    _runtime_active_manifest_path,
    _selection_output,
    _send_write_plan_output,
    _sufficiency_output,
    _write_plan_output,
)
from tests.support.fakes import DeterministicUUID, FakeClockPort, FakeGoogleGateway
from tests.support.fixtures import ProductFixtureSnapshotLoader
from tests.support.legacy_write.write_actions import (
    PrepareWriteRetryService,
    RequestRunCancellationService,
)
from tests.support.legacy_write_action_mutation import (
    ModifyWriteActionService,
    RejectWriteActionService,
)
from tests.support.legacy_write_approval import ApproveWriteActionService
from tests.support.workflow_admission import build_test_admission_callbacks

from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    RESUME_CONTRACT_VERSION,
)
from google_work_agent.adapters.langgraph.registry.checkpoint_target_resolver import (
    NativeCheckpointTargetResolver,
)
from google_work_agent.adapters.langgraph.registry.node_registry import NodeRegistry
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    ResumeTargetRegistry,
)
from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.adapters.readiness.composite import (
    StaticReadinessAggregator,
)
from google_work_agent.adapters.system.memory.sse_event_buffer import InMemorySseEventBuffer
from google_work_agent.adapters.system.sqlite_checkpoint import SqliteCheckpointAdapter
from google_work_agent.api.app import create_app
from google_work_agent.api.composition import build_production_runtime
from google_work_agent.api.container import ApiContainer
from google_work_agent.api.security.sessions import calculate_session_digest
from google_work_agent.application.orchestration.handoff_contracts import (
    ActionPlanDraftV1,
    RequestIntentV2,
)
from google_work_agent.application.use_cases.conversation.create_conversation import (
    CreateConversationHandler,
)
from google_work_agent.application.use_cases.conversation.get_conversation_history import (
    GetConversationHistoryHandler,
)
from google_work_agent.application.use_cases.conversation.list_conversations import (
    ListConversationsHandler,
)
from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    IssueSelectionHandle,
    IssueSelectionHandleCommand,
)
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandle,
)
from google_work_agent.application.use_cases.run.get_execution_context import (
    GetExecutionContextHandler,
)
from google_work_agent.ports.system.api_access_port import (
    AccessDecision,
    ApiRequestContext,
    EndpointPolicy,
)
from google_work_agent.ports.system.readiness_port import (
    ReadinessCheckResult,
    ReadinessReport,
    ReadinessState,
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
    # "resource_id" is provider-generated (assigned only after the write
    # dispatches) and is never a business argument Planning may author --
    # see planning_tool_schemas._GMAIL_DRAFT_PAYLOAD's additionalProperties:
    # False allowlist. It belongs only in "expected" (the verification
    # target), not in "arguments" (the Tool call input).
    arguments_payload = {
        "to": ["pm@example.com"],
        "subject": "Product E2E draft",
        "body": "Deterministic product integration draft.",
    }
    payload = {"resource_id": "draft-product-e2e", **arguments_payload}
    plan["actions"][0].update(
        {
            "effect": "CREATE",
            "tool_name": "gmail_create_draft",
            "arguments": {"payload": arguments_payload},
            "expected": {
                "resource_type": "gmail_draft",
                "resource_id": "draft-product-e2e",
                "parent_id": None,
                "version": "1",
                "payload": payload,
            },
            "evidence_refs": ["evidence-seg-3"],
            "resource_refs": ["gmail_message:message-project-1"],
        }
    )
    plan["evidence_refs"] = ["evidence-seg-3"]
    plan["resource_refs"] = [
        {
            "resource_handle": "gmail_message:message-project-1",
            "resource_type": "gmail_message",
            "resource_id": "message-project-1",
        }
    ]
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


def _gmail_send_plan() -> ActionPlanDraftV1:
    plan = _send_write_plan_output()
    plan["actions"][0]["evidence_refs"] = ["evidence-seg-1"]
    plan["actions"][0]["resource_refs"] = ["gmail_draft:draft-followup"]
    plan["evidence_refs"] = ["evidence-seg-1"]
    plan["resource_refs"] = [
        {
            "resource_handle": "gmail_draft:draft-followup",
            "resource_type": "gmail_draft",
            "resource_id": "draft-followup",
        }
    ]
    return plan


def _gmail_draft_selection_output() -> dict[str, object]:
    return {
        "schema_version": 2,
        "selected_segment_ids": ["seg-1"],
        "evidence_drafts": [
            {
                "segment_id": "seg-1",
                "role": "SUPPORTS",
                "relevance_reason": "The selected draft is the exact Gmail send target.",
            }
        ],
        "excluded_segment_ids": [],
    }


def _gmail_draft_analysis_output() -> dict[str, object]:
    result = _gmail_analysis_output()
    finding = cast(dict[str, object], cast(list[object], result["findings"])[0])
    finding["evidence_refs"] = ["evidence-seg-1"]
    finding["resource_refs"] = ["gmail_draft:draft-followup"]
    finding["related_resource_handles"] = ["gmail_draft:draft-followup"]
    finding["segment_refs"] = ["seg-1"]
    result["evidence_refs"] = ["evidence-seg-1"]
    result["resource_refs"] = [
        {
            "resource_handle": "gmail_draft:draft-followup",
            "resource_type": "gmail_draft",
            "resource_id": "draft-followup",
        }
    ]
    result["segment_refs"] = [
        {"segment_id": "seg-1", "resource_handle": "gmail_draft:draft-followup"}
    ]
    return result


def _calendar_create_plan() -> ActionPlanDraftV1:
    plan = _write_plan_output()
    # "resource_id" (provider-generated) and "status" (not in
    # planning_tool_schemas._CALENDAR_CREATE_PAYLOAD's allowlist -- Google
    # always creates events as "confirmed") are not business arguments
    # Planning may author; they belong only in "expected", not "arguments".
    arguments_payload = {
        "title": "Product E2E event",
        "start": "2026-11-02T09:00:00-08:00",
        "end": "2026-11-02T09:30:00-08:00",
    }
    payload = {
        "resource_id": "event-product-e2e",
        "status": "confirmed",
        **arguments_payload,
    }
    plan["actions"][0].update(
        {
            "effect": "CREATE",
            "tool_name": "calendar_create_event",
            "arguments": {"calendar_id": "calendar-primary", "payload": arguments_payload},
            "expected": {
                "resource_type": "calendar_event",
                "resource_id": "event-product-e2e",
                "parent_id": "calendar-primary",
                "version": "1",
                "payload": payload,
            },
            "target_resource_ref_id": None,
            "evidence_refs": ["evidence-seg-1"],
            "resource_refs": ["calendar_event:event-focus"],
        }
    )
    plan["evidence_refs"] = ["evidence-seg-1"]
    plan["resource_refs"] = [
        {
            "resource_handle": "calendar_event:event-focus",
            "resource_type": "calendar_event",
            "resource_id": "event-focus",
        }
    ]
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


def _intent_for_write_operation(write_operation: str) -> RequestIntentV2:
    if write_operation == "create_gmail_draft":
        return _action_intent(resource="GMAIL_DRAFT", effect="CREATE")
    if write_operation == "send_gmail":
        return _action_intent(resource="GMAIL_MESSAGE", effect="SEND")
    if write_operation == "create_task":
        return _action_intent(resource="TASK", effect="CREATE")
    if write_operation == "update_task":
        return _action_intent(resource="TASK", effect="UPDATE")
    if write_operation == "delete_task":
        return _action_intent(resource="TASK", effect="DELETE")
    if write_operation == "create_calendar_event":
        return _action_intent(resource="CALENDAR_EVENT", effect="CREATE")
    if write_operation == "update_calendar_event":
        return _action_intent(resource="CALENDAR_EVENT", effect="UPDATE", source="CALENDAR")
    if write_operation == "delete_calendar_event":
        return _action_intent(resource="CALENDAR_EVENT", effect="DELETE", source="CALENDAR")
    raise AssertionError(f"unsupported write operation fixture: {write_operation}")


@pytest.mark.parametrize(
    ("plan_factory", "context_family", "write_operation", "verification_operation"),
    [
        (_gmail_draft_plan, "GMAIL", "create_gmail_draft", "get_gmail_draft"),
        (
            _gmail_send_plan,
            "GMAIL",
            "send_gmail",
            "search_by_recovery_fingerprint",
        ),
        (_write_plan_output, "TASKS", "create_task", "get_task"),
        (_task_update_plan, "TASKS", "update_task", "get_task"),
        (_task_delete_plan, "TASKS", "delete_task", "get_task"),
        (_calendar_create_plan, "CALENDAR", "create_calendar_event", "get_calendar_event"),
        (_calendar_update_plan, "CALENDAR", "update_calendar_event", "get_calendar_event"),
        (_delete_write_plan_output, "CALENDAR", "delete_calendar_event", "get_calendar_event"),
    ],
)
def test_product_api_approval_resumes_langgraph_and_verifies_one_google_write(
    tmp_path: Path,
    plan_factory: Callable[[], ActionPlanDraftV1],
    context_family: Literal["TASKS", "GMAIL", "CALENDAR"],
    write_operation: str,
    verification_operation: str,
) -> None:
    database_path = _seed_product_database(tmp_path)
    clock = FakeClockPort(1000)
    unit_of_work_factory = sqlite_unit_of_work_factory(database_path)
    gateway = FakeGoogleGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    if context_family == "CALENDAR":
        context_payloads = [
            _calendar_selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _calendar_analysis_output(),
        ]
    elif write_operation == "send_gmail":
        context_payloads = [
            _gmail_draft_selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _gmail_draft_analysis_output(),
        ]
    elif context_family == "GMAIL":
        context_payloads = [
            _gmail_selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _gmail_analysis_output(),
        ]
    else:
        context_payloads = [
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
        ]
    llm_payloads = [
        _intent_for_write_operation(write_operation),
        *context_payloads,
        plan_factory(),
        _review_output("PASS"),
    ]
    resume_target_registry = ResumeTargetRegistry(
        node_registry=NodeRegistry(graph_version=RESUME_CONTRACT_VERSION),
        graph_version=RESUME_CONTRACT_VERSION,
    )
    checkpoint = SqliteCheckpointAdapter(
        database_path,
        now_ms=clock.now_ms,
        target_resolver=NativeCheckpointTargetResolver(resume_target_registry),
    )
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=llm_payloads,
        gateway=gateway,
        checkpoint_port=checkpoint,
        prompt_manifest_path=_runtime_active_manifest_path(tmp_path),
    )
    get_execution_context = GetExecutionContextHandler(unit_of_work_factory=unit_of_work_factory)
    publisher = InMemorySseEventBuffer(service_instance_id="svc-product", capacity_per_run=32)
    id_generator = DeterministicUUID(prefix="api")

    checkpoint, materialize, invoke = build_test_admission_callbacks(
        checkpoint_path=database_path,
        get_execution_context=get_execution_context,
        unit_of_work_factory=unit_of_work_factory,
        workflow_runtime=runtime,
        event_publisher=publisher,
        now_ms=clock.now_ms,
        checkpoint=checkpoint,
    )

    production_runtime = build_production_runtime(
        unit_of_work_factory=unit_of_work_factory,
        id_factory=id_generator.next_id,
        checkpoint=checkpoint,
        materialize_admission_checkpoint=materialize,
        invoke_semantic_owner=invoke,
        resume_target_registry=resume_target_registry,
        lookup_unknown_result=lambda command: None,
        recover_existing_result=lambda command: None,
        resolve_as_failed=lambda command: None,
        materialize_recovery_snapshot=lambda tool_name, arguments, resource_id: None,
        now_ms=clock.now_ms,
        reconciliation_interval_seconds=0.2,
    )
    container = ApiContainer(
        unit_of_work_factory=unit_of_work_factory,
        current_account_id_provider=lambda: "account-1",
        create_conversation_handler=CreateConversationHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        list_conversations_handler=ListConversationsHandler(
            unit_of_work_factory=unit_of_work_factory,
        ),
        get_conversation_history_handler=GetConversationHistoryHandler(
            unit_of_work_factory=unit_of_work_factory,
        ),
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="resume-contract-v1",
        schedule_run_execution=production_runtime.schedule_run_execution,
        resume_target_registry=resume_target_registry,
        resolve_selection_handle=ResolveSelectionHandle(
            signing_secret=b"s" * 32,
            service_instance_id="svc-product",
            now_ms=clock.now_ms,
        ),
        action_gateway=gateway,
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
        resume_run_service=lambda command: command,
        workflow_runtime=runtime,
        event_publisher=publisher,
        readiness_aggregator=StaticReadinessAggregator(
            ReadinessReport(
                state=ReadinessState.READY,
                checks=(ReadinessCheckResult(name="sqlite", state=ReadinessState.READY),),
            )
        ),
        api_access_guard=_AllowGuard(),
        clock=clock,
        id_generator=id_generator,
        release_version="test",
        environment="test",
        service_instance_id="svc-product",
        local_bind_host="127.0.0.1",
        local_bind_port=8780,
        client_address_resolver=lambda _request: "127.0.0.1",
    )

    try:
        with TestClient(create_app(container), base_url="http://127.0.0.1:8780") as client:
            selection_handle = None
            if write_operation == "send_gmail":
                session_token = "product-e2e-session"
                client.cookies.set("gwa_session", session_token)
                selection_handle = IssueSelectionHandle(
                    signing_secret=b"s" * 32,
                    service_instance_id="svc-product",
                    now_ms=clock.now_ms,
                    ttl_ms=30_000,
                )(
                    IssueSelectionHandleCommand(
                        session_digest=calculate_session_digest(session_token),
                        account_id="account-1",
                        connector_id="google_workspace",
                        resource_type="gmail_draft",
                        resource_id="draft-followup",
                        parent_resource_id="thread-project",
                        version_token="2",
                    )
                )
            run_id = _create_conversation_and_run(client, selection_handle=selection_handle)
            waiting = _wait_for_snapshot(client, run_id, "WAITING_APPROVAL")
            assert production_runtime.workflow_execution.await_drained(5_000)
            production_runtime.workflow_handoff_reconciliation_loop.start()
            action = _first_action(waiting)
            action_id = cast(str, action["action_id"])
            reads_before_approval = gateway.count_calls(verification_operation)

            approval_body = {
                "command_id": "approve-command-1",
                "expected_version": action["version"],
                "ttl_ms": 30_000,
                "api_contract_version": "1",
                "calendar_conflict_acknowledged": write_operation
                in {"create_calendar_event", "update_calendar_event"},
            }
            approved = client.post(f"/api/v1/actions/{action_id}/approve", json=approval_body)
            assert approved.status_code == 200
            effective_approval_body = approval_body
            completed = _wait_for_snapshot(client, run_id, "COMPLETED")
            # Queue drain is process-local evidence, not durable workflow
            # completion.  Assert it only after the Domain snapshot proves
            # that any required admission redrive has settled.
            assert production_runtime.workflow_execution.await_drained(5_000)

            assert _first_action(completed)["status"] == "VERIFIED"
            assert gateway.count_calls(write_operation) == 1
            assert gateway.count_calls(verification_operation) >= reads_before_approval + 1
            replay = client.post(
                f"/api/v1/actions/{action_id}/approve", json=effective_approval_body
            )
            assert replay.status_code == 200
            # ttl_ms is deprecated/server-ignored and excluded from the request
            # hash (approval lifetime is server-owned via
            # AppSettings.approval_ttl_minutes -- see
            # api/routes/actions.py:approve, which pops it before hashing), so
            # varying only ttl_ms can no longer produce a hash mismatch.
            # duplicate_acknowledged is an actual hashed request field.
            conflict = client.post(
                f"/api/v1/actions/{action_id}/approve",
                json={**effective_approval_body, "duplicate_acknowledged": True},
            )
            assert conflict.status_code == 409
            time.sleep(0.05)
            assert gateway.count_calls(write_operation) == 1
    finally:
        production_runtime.workflow_handoff_reconciliation_loop.stop()
        production_runtime.workflow_execution.close()

    connection = connect_sqlite(database_path)
    try:
        counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM approvals),
                (SELECT COUNT(*) FROM execution_attempts),
                (SELECT COUNT(*) FROM verifications),
                (SELECT COUNT(*) FROM audit_events WHERE action_id = ?),
                (SELECT COUNT(*) FROM trace_events WHERE action_id = ?);
            """,
            (action_id, action_id),
        ).fetchone()
        expected_audit_count = 8 if write_operation == "create_task" else 6
        if write_operation in {"create_calendar_event", "update_calendar_event"}:
            expected_audit_count += 2
        # The intentional same-command_id/different-hash approve retry above
        # (ttl_ms changed) now also records one COMMAND_REJECTED_HASH_MISMATCH
        # audit event for this action.
        expected_audit_count += 1
        assert tuple(counts) == (
            1,
            1,
            1,
            expected_audit_count,
            4,
        )
    finally:
        connection.close()

    event_types = [
        event.event_type
        for event in publisher.list_after(run_id, last_event_id=None, limit=32).events
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


def _create_conversation_and_run(
    client: TestClient, *, selection_handle: str | None = None
) -> str:
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
            "request_text": "Send the selected Gmail draft.",
            "entry_mode": "RESOURCE_SELECTED" if selection_handle is not None else "AGENT_SEARCH",
            "selected_resource_handles": [] if selection_handle is None else [selection_handle],
            "requested_mode": "AUTO",
            "api_contract_version": "1",
        },
    )
    assert started.status_code == 202
    return cast(str, started.json()["run_id"])


def _wait_for_snapshot(client: TestClient, run_id: str, expected_status: str) -> dict[str, object]:
    # One same-process durable redrive may follow SQLite's configured
    # five-second busy timeout; keep the product wait above that retry horizon.
    deadline = time.monotonic() + 30
    latest: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/runs/{run_id}")
        assert response.status_code == 200
        latest = response.json()["snapshot"]
        if latest["status"] == expected_status:
            return latest
        # Snapshot reads use the same SQLite file as native checkpoints in
        # this component topology. A bounded UI-like polling cadence leaves
        # the background checkpoint writer a fair writer slot instead of
        # creating an artificial continuous BEGIN IMMEDIATE writer loop.
        time.sleep(0.05)
    raise AssertionError(f"run did not reach {expected_status}: {latest}")


def _first_action(snapshot: dict[str, object]) -> dict[str, object]:
    actions = snapshot.get("actions")
    if not isinstance(actions, list) or not actions or not isinstance(actions[0], dict):
        raise AssertionError("run snapshot must contain at least one action object")
    action = actions[0]
    if not all(isinstance(key, str) for key in action):
        raise AssertionError("action keys must be strings")
    return cast(dict[str, object], action)
