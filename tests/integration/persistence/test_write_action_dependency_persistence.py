"""GAP-F3 prerequisite: WRITE Action Dependency Persistence.

Covers the fix for the gap tracked in `start_run.py`'s
`_revoke_stale_dependent_approvals` and `write_actions.py`'s
`_propagate_dependency_blocked` docstrings: `SaveWritePlanService` now
persists `depends_on_action_ids` into `action_dependencies` for WRITE
plans (previously only READ-only plans did), so those two pre-existing
safety nets become reachable through the real production path instead of
only through a directly-seeded dependency row.
"""

from pathlib import Path

import pytest

from google_work_agent.adapters.connectors.google.workspace.composition import (
    GOOGLE_WORKSPACE_CONNECTOR_ID,
)
from google_work_agent.adapters.persistence import (
    apply_migrations,
    connect_sqlite,
    sqlite_unit_of_work_factory,
)
from google_work_agent.application.use_cases.action.write_approval_contracts import (
    ApproveWriteActionCommand,
)
from google_work_agent.application.use_cases.execution_attempt.write_execution_contracts import (
    ClaimWriteActionCommand,
    MarkWriteActionFailedCommand,
)
from google_work_agent.application.use_cases.plan.publish_plan import PublishPlanHandler
from google_work_agent.application.use_cases.plan.save_write_plan import (
    SaveWritePlanService,
)
from google_work_agent.application.use_cases.plan.write_plan_contracts import (
    PublishWritePlanCommand,
    SaveWritePlanCommand,
    WriteActionDraft,
    WriteEvidenceDraft,
)
from google_work_agent.domain.evidence.model import EvidenceOriginType
from google_work_agent.ports.persistence.action_repository import dependency_ids_for_action
from google_work_agent.ports.persistence.trace_event_repository import TraceEventCursor
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from tests.support.fakes import FakeClockPort
from tests.support.legacy_write.write_claim import ClaimWriteActionService
from tests.support.legacy_write.write_result_persistence import (
    MarkWriteActionFailedService,
)
from tests.support.legacy_write_approval import ApproveWriteActionService

_TASK_PAYLOAD = {"title": "Send summary", "notes": "draft notes"}


def _dependency_ids(unit_of_work: UnitOfWork, action_id: str) -> tuple[str, ...]:
    action = unit_of_work.actions.get(action_id)
    assert action is not None
    actions = unit_of_work.actions.list_for_plan(action.plan_id)
    return dependency_ids_for_action(unit_of_work.actions, actions, action_id)


@pytest.fixture()
def dependency_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "write-action-dependencies.db"
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            """
            INSERT INTO google_accounts (id, email, display_name, connected_at_ms)
            VALUES ('account-1', 'user@example.com', 'User', 1);
            """
        )
        connection.execute(
            """
            INSERT INTO conversations (id, account_id, title, created_at_ms, updated_at_ms)
            VALUES ('conversation-1', 'account-1', 'Conversation', 1, 1);
            """
        )
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            )
            VALUES (
                'run-1', 'conversation-1', 'AGENT_SEARCH', 'PLANNING', 'thread-1',
                'AUTO', '{}', 0, 100
            );
            """
        )
    finally:
        connection.close()
    return database_path


def _task_draft(
    action_id: str, position: int, *, depends_on_action_ids: tuple[str, ...] = ()
) -> WriteActionDraft:
    return WriteActionDraft(
        action_id=action_id,
        connector_id=GOOGLE_WORKSPACE_CONNECTOR_ID,
        position=position,
        tool_name="tasks_create_task",
        arguments={"task_list_id": "task-list-default", "payload": dict(_TASK_PAYLOAD)},
        expected={"resource_type": "task", "resource_id": None, "payload": dict(_TASK_PAYLOAD)},
        evidence_ids=(f"evidence-{action_id}",),
        depends_on_action_ids=depends_on_action_ids,
    )


def _evidence(*action_ids: str) -> tuple[WriteEvidenceDraft, ...]:
    return tuple(
        WriteEvidenceDraft(
            evidence_id=f"evidence-{action_id}",
            origin_type=EvidenceOriginType.DERIVED,
            kind="USER_REQUEST",
            excerpt="Create a task.",
        )
        for action_id in action_ids
    )


def test_save_write_plan_persists_a_single_dependency_edge(dependency_database: Path) -> None:
    clock = FakeClockPort(initial_ms=1_000)
    unit_of_work_factory = sqlite_unit_of_work_factory(dependency_database)
    save_service = SaveWritePlanService(
        unit_of_work_factory=unit_of_work_factory, now_ms=clock.now_ms
    )

    save_response = save_service(
        SaveWritePlanCommand(
            command_id="save-single-edge",
            request_hash="a1" * 32,
            plan_id="plan-single-edge",
            run_id="run-1",
            revision_no=1,
            summary_text="upstream and dependent task",
            expected_run_version=0,
            actions=(
                _task_draft("action-a", 1),
                _task_draft("action-b", 2, depends_on_action_ids=("action-a",)),
            ),
            evidence=_evidence("action-a", "action-b"),
        )
    )
    assert save_response.applied is True

    with unit_of_work_factory() as unit_of_work:
        b_dependencies = _dependency_ids(unit_of_work, "action-b")
        a_dependents = unit_of_work.actions.list_dependents("action-a")
        a_dependencies = _dependency_ids(unit_of_work, "action-a")
        b_dependents = unit_of_work.actions.list_dependents("action-b")

    assert b_dependencies == ("action-a",)
    assert a_dependents == ("action-b",)
    assert a_dependencies == ()
    assert b_dependents == ()


def test_save_write_plan_persists_a_chain_of_dependencies(dependency_database: Path) -> None:
    clock = FakeClockPort(initial_ms=1_000)
    unit_of_work_factory = sqlite_unit_of_work_factory(dependency_database)
    save_service = SaveWritePlanService(
        unit_of_work_factory=unit_of_work_factory, now_ms=clock.now_ms
    )

    save_response = save_service(
        SaveWritePlanCommand(
            command_id="save-chain",
            request_hash="a2" * 32,
            plan_id="plan-chain",
            run_id="run-1",
            revision_no=1,
            summary_text="A -> B -> C chain",
            expected_run_version=0,
            actions=(
                _task_draft("action-a", 1),
                _task_draft("action-b", 2, depends_on_action_ids=("action-a",)),
                _task_draft("action-c", 3, depends_on_action_ids=("action-b",)),
            ),
            evidence=_evidence("action-a", "action-b", "action-c"),
        )
    )
    assert save_response.applied is True

    with unit_of_work_factory() as unit_of_work:
        a_dependencies = _dependency_ids(unit_of_work, "action-a")
        b_dependencies = _dependency_ids(unit_of_work, "action-b")
        c_dependencies = _dependency_ids(unit_of_work, "action-c")
        a_dependents = unit_of_work.actions.list_dependents("action-a")
        b_dependents = unit_of_work.actions.list_dependents("action-b")
        c_dependents = unit_of_work.actions.list_dependents("action-c")

    assert a_dependencies == ()
    assert b_dependencies == ("action-a",)
    assert c_dependencies == ("action-b",)
    assert a_dependents == ("action-b",)
    assert b_dependents == ("action-c",)
    assert c_dependents == ()


def test_save_write_plan_without_dependencies_persists_no_rows(dependency_database: Path) -> None:
    clock = FakeClockPort(initial_ms=1_000)
    unit_of_work_factory = sqlite_unit_of_work_factory(dependency_database)
    save_service = SaveWritePlanService(
        unit_of_work_factory=unit_of_work_factory, now_ms=clock.now_ms
    )

    save_response = save_service(
        SaveWritePlanCommand(
            command_id="save-no-deps",
            request_hash="a3" * 32,
            plan_id="plan-no-deps",
            run_id="run-1",
            revision_no=1,
            summary_text="two independent tasks",
            expected_run_version=0,
            actions=(_task_draft("action-x", 1), _task_draft("action-y", 2)),
            evidence=_evidence("action-x", "action-y"),
        )
    )
    assert save_response.applied is True

    with unit_of_work_factory() as unit_of_work:
        x_dependencies = _dependency_ids(unit_of_work, "action-x")
        y_dependencies = _dependency_ids(unit_of_work, "action-y")
        x_dependents = unit_of_work.actions.list_dependents("action-x")
        y_dependents = unit_of_work.actions.list_dependents("action-y")

    assert x_dependencies == ()
    assert y_dependencies == ()
    assert x_dependents == ()
    assert y_dependents == ()


def test_mark_write_action_failed_propagates_dependency_blocked_through_persisted_graph(
    dependency_database: Path,
) -> None:
    """08-sequence-design.md section 12 requires a rejected/failed action's
    dependents to become DEPENDENCY_BLOCKED. `_propagate_dependency_blocked`
    already implements this, but was unreachable for WRITE actions because
    `action_dependencies` was never populated. This proves the real save ->
    publish -> approve -> claim -> fail path now reaches it end to end.
    """

    clock = FakeClockPort(initial_ms=1_000)
    unit_of_work_factory = sqlite_unit_of_work_factory(dependency_database)
    save_service = SaveWritePlanService(
        unit_of_work_factory=unit_of_work_factory, now_ms=clock.now_ms
    )
    publish_service = PublishPlanHandler(
        unit_of_work_factory=unit_of_work_factory, now_ms=clock.now_ms
    )
    approve_service = ApproveWriteActionService(
        unit_of_work_factory=unit_of_work_factory, now_ms=clock.now_ms
    )
    claim_service = ClaimWriteActionService(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=clock.now_ms,
        signing_secret="dependency-blocked-secret",
        service_instance_id="dependency-blocked-svc",
    )
    mark_failed_service = MarkWriteActionFailedService(
        unit_of_work_factory=unit_of_work_factory, now_ms=clock.now_ms
    )

    save_response = save_service(
        SaveWritePlanCommand(
            command_id="save-blocked",
            request_hash="a4" * 32,
            plan_id="plan-blocked",
            run_id="run-1",
            revision_no=1,
            summary_text="upstream fails, dependent must block",
            expected_run_version=0,
            actions=(
                _task_draft("action-upstream", 1),
                _task_draft("action-dependent", 2, depends_on_action_ids=("action-upstream",)),
            ),
            evidence=_evidence("action-upstream", "action-dependent"),
        )
    )
    assert save_response.applied is True

    publish_response = publish_service(
        PublishWritePlanCommand(
            command_id="publish-blocked",
            request_hash="a5" * 32,
            plan_id="plan-blocked",
            run_id="run-1",
            expected_run_version=0,
        )
    )
    assert publish_response.applied is True

    approve_response = approve_service(
        ApproveWriteActionCommand(
            command_id="approve-upstream",
            request_hash="a6" * 32,
            action_id="action-upstream",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-upstream",
            idempotency_key="b1" * 32,
        )
    )
    assert approve_response.applied is True
    assert approve_response.action_status == "APPROVED"

    claim_response = claim_service(
        ClaimWriteActionCommand(
            command_id="claim-upstream",
            request_hash="a7" * 32,
            action_id="action-upstream",
            expected_version=1,
            source_snapshot={},
            attempt_id="attempt-upstream",
            nonce="nonce-upstream",
        )
    )
    assert claim_response.applied is True
    assert claim_response.action_status == "EXECUTING"

    fail_result = mark_failed_service(
        MarkWriteActionFailedCommand(
            command_id="fail-upstream",
            request_hash="a8" * 32,
            action_id="action-upstream",
            attempt_id="attempt-upstream",
            expected_action_version=2,
            expected_attempt_version=0,
            error_code="GOOGLE_API_ERROR",
            error_detail="simulated upstream dispatch failure",
        )
    )
    assert fail_result.applied is True
    assert fail_result.action_status == "FAILED"

    with unit_of_work_factory() as unit_of_work:
        dependent_action = unit_of_work.actions.get("action-dependent")
        dependent_trace_events = unit_of_work.traces.list_page(
            TraceEventCursor(run_id="run-1"), 100
        )

    assert dependent_action is not None
    assert dependent_action.status == "DEPENDENCY_BLOCKED"
    blocked_events = [
        event
        for event in dependent_trace_events
        if event.action_id == "action-dependent" and event.event_type == "WRITE_DEPENDENCY_BLOCKED"
    ]
    assert len(blocked_events) == 1
