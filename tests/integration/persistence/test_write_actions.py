"""Shared Write integration fixtures and compatibility exports."""

# ruff: noqa: F401

import sqlite3
from collections.abc import Mapping
from json import loads
from pathlib import Path
from typing import cast

import pytest

from google_work_agent.adapters.connectors.google_workspace_execution import (
    GoogleWorkspaceExecutionBackend,
)
from google_work_agent.adapters.persistence import (
    apply_migrations,
    connect_sqlite,
    sqlite_unit_of_work_factory,
)
from google_work_agent.application import (
    ApproveWriteActionCommand,
    ApproveWriteActionService,
    ClaimWriteActionCommand,
    ClaimWriteActionService,
    ExecuteWriteActionService,
    FinalizeRunCancellationCommand,
    FinalizeRunCancellationService,
    MarkWriteActionUnknownResultCommand,
    MarkWriteActionUnknownResultService,
    PreflightWriteActionService,
    PrepareWriteRetryCommand,
    PrepareWriteRetryService,
    PublishWritePlanCommand,
    PublishWritePlanService,
    RecoverUnknownCreateActionCommand,
    RecoverUnknownCreateActionService,
    RecoverUnknownDeleteActionCommand,
    RecoverUnknownDeleteActionService,
    RecoverUnknownSendActionCommand,
    RecoverUnknownSendActionService,
    RecoverUnknownUpdateActionCommand,
    RecoverUnknownUpdateActionService,
    RecoveryResolutionKind,
    RequestRunCancellationCommand,
    RequestRunCancellationService,
    RequireWriteReauthCommand,
    RequireWriteReauthService,
    ResolveMismatchRecoveryCommand,
    ResolveMismatchRecoveryService,
    SaveWritePlanCommand,
    SaveWritePlanService,
    StoreWriteActionSuccessCommand,
    StoreWriteActionSuccessService,
    VerifyWriteActionCommand,
    VerifyWriteActionService,
    WriteActionDraft,
    WriteActionResponse,
    WriteEvidenceDraft,
)
from google_work_agent.application.queries import QueryService
from google_work_agent.application.write_actions import (
    DeliveryCertainty,
    classify_write_delivery,
    is_reauth_required_error,
)
from google_work_agent.domain import (
    CalendarWorkHours,
    InvariantViolationError,
    PolicyViolationError,
    ResultCode,
    RunCommand,
    RunStatus,
)
from google_work_agent.ports import (
    EvidenceOriginType,
    FreeBusyCalendar,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGateway,
    GoogleWorkspaceGatewayError,
    ResourcePage,
    ResourceSnapshot,
    ResourceType,
    TimeRange,
)
from tests.support.fakes import (
    FakeClock,
    FakeGoogleGateway,
    GoogleGatewayFault,
    GoogleGatewayFaultKind,
)
from tests.support.fixtures import ProductFixtureSnapshotLoader

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "product"


@pytest.fixture()
def write_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "write-actions.db"
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


@pytest.fixture()
def fixture_gateway() -> FakeGoogleGateway:
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    return FakeGoogleGateway(snapshot)


class _TransactionCheckingGateway:
    def __init__(
        self,
        *,
        delegate: FakeGoogleGateway,
        database_path: Path,
        after_get_sql: str | None = None,
    ) -> None:
        self._delegate = delegate
        self._database_path = database_path
        self._after_get_sql = after_get_sql

    def get_task(self, *, task_list_id: str, task_id: str) -> ResourceSnapshot:
        _assert_can_open_sqlite_write_transaction(self._database_path)
        snapshot = self._delegate.get_task(task_list_id=task_list_id, task_id=task_id)
        if self._after_get_sql is not None:
            connection = connect_sqlite(self._database_path)
            try:
                connection.execute(self._after_get_sql)
                connection.commit()
            finally:
                connection.close()
        return snapshot

    def get_gmail_message(self, *, message_id: str) -> ResourceSnapshot:
        _assert_can_open_sqlite_write_transaction(self._database_path)
        return self._delegate.get_gmail_message(message_id=message_id)

    def get_gmail_draft(self, *, draft_id: str) -> ResourceSnapshot:
        _assert_can_open_sqlite_write_transaction(self._database_path)
        return self._delegate.get_gmail_draft(draft_id=draft_id)

    def get_calendar_event(self, *, calendar_id: str, event_id: str) -> ResourceSnapshot:
        _assert_can_open_sqlite_write_transaction(self._database_path)
        return self._delegate.get_calendar_event(calendar_id=calendar_id, event_id=event_id)


def _assert_can_open_sqlite_write_transaction(database_path: Path) -> None:
    connection = sqlite3.connect(database_path, timeout=0, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE;")
        connection.execute("ROLLBACK;")
    finally:
        connection.close()


def _seed_write_terminal_status(
    *, database_path: Path, action_id: str, terminal_status: str
) -> None:
    connection = connect_sqlite(database_path)
    try:
        approval_id = f"approval-{action_id}"
        attempt_id = f"attempt-{action_id}"
        connection.execute(
            "UPDATE actions SET status = 'APPROVED', version = 1 WHERE id = ?;", (action_id,)
        )
        connection.execute(
            """
            INSERT INTO approvals (
                id, action_id, approval_no, action_version, status, approved_by_account_id,
                arguments_snapshot_json, canonical_arguments_hash, source_snapshot_json,
                source_snapshot_hash, policy_version, tool_schema_version, idempotency_key,
                recovery_fingerprint, approved_at_ms, expires_at_ms
            ) VALUES (?, ?, 1, 1, 'ACTIVE', 'account-1', '{}', ?, '{}', ?, 'p1', 'v1', ?, ?, 1, 2);
            """,
            (
                approval_id,
                action_id,
                "a" * 64,
                "b" * 64,
                approval_id.ljust(64, "x")[:64],
                "c" * 64,
            ),
        )
        connection.execute(
            "UPDATE approvals SET status = 'CONSUMED', consumed_at_ms = 1 WHERE id = ?;",
            (approval_id,),
        )
        connection.execute(
            "UPDATE actions SET status = 'EXECUTING', version = 2 WHERE id = ?;", (action_id,)
        )
        connection.execute(
            """
            INSERT INTO execution_attempts (id, approval_id, attempt_no, status, started_at_ms)
            VALUES (?, ?, 1, 'CLAIMED', 1);
            """,
            (attempt_id, approval_id),
        )
        attempt_status = "FAILED" if terminal_status == "FAILED" else "SUCCEEDED"
        connection.execute(
            "UPDATE execution_attempts SET status = ? WHERE id = ?;",
            (attempt_status, attempt_id),
        )
        if terminal_status == "FAILED":
            connection.execute(
                "UPDATE actions SET status = 'FAILED', version = 3 WHERE id = ?;", (action_id,)
            )
        else:
            connection.execute(
                "UPDATE actions SET status = 'EXECUTED', version = 3 WHERE id = ?;", (action_id,)
            )
            connection.execute(
                """
                INSERT INTO verifications (
                    id, execution_attempt_id, verification_no, status, normalizer_version,
                    expected_json, actual_json, diff_json, verified_at_ms
                ) VALUES (?, ?, 1, 'MISMATCH', 'v1', '{}', '{}', '[]', 2);
                """,
                (f"verification-{action_id}", attempt_id),
            )
            connection.execute(
                "UPDATE actions SET status = 'MISMATCH', version = 4 WHERE id = ?;", (action_id,)
            )
        connection.commit()
    finally:
        connection.close()


def _insert_action_sibling(
    *,
    database_path: Path,
    source_action_id: str,
    sibling_action_id: str,
    status: str,
) -> None:
    connection = connect_sqlite(database_path)
    try:
        connection.execute(
            """
            INSERT INTO actions (
                id, plan_id, position, tool_name, effect_type, approval_requirement,
                verification_policy, recovery_policy, target_resource_ref_id, status,
                arguments_json, arguments_hash, expected_json, risk_json, version,
                created_at_ms, updated_at_ms
            )
            SELECT
                ?, plan_id, 2, tool_name, effect_type, approval_requirement,
                verification_policy, recovery_policy, target_resource_ref_id, ?,
                arguments_json, arguments_hash, expected_json, risk_json, 0,
                created_at_ms, updated_at_ms
            FROM actions WHERE id = ?;
            """,
            (sibling_action_id, status, source_action_id),
        )
        connection.commit()
    finally:
        connection.close()


def _cancel_marker_count(database_path: Path) -> int:
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            """
            SELECT COUNT(*)
            FROM audit_events
            WHERE run_id = 'run-1'
              AND event_type = 'RUN_CANCELLATION_REQUESTED'
              AND outcome = 'TRANSITION_APPLIED';
            """
        ).fetchone()
        return int(row[0])
    finally:
        connection.close()


def _action_cancelled_audit_count(database_path: Path) -> int:
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type = 'ACTION_CANCELLED';"
        ).fetchone()
        return int(row[0])
    finally:
        connection.close()


def _cancel_child_snapshot(database_path: Path) -> tuple[object, ...]:
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            """
            SELECT
                (SELECT status FROM runs WHERE id = 'run-1'),
                (SELECT version FROM runs WHERE id = 'run-1'),
                (SELECT status FROM plans WHERE id = 'plan-atomic-cancel'),
                (SELECT status FROM actions WHERE id = 'action-atomic-cancel'),
                (SELECT version FROM actions WHERE id = 'action-atomic-cancel'),
                (SELECT status FROM approvals WHERE id = 'approval-atomic-cancel');
            """
        ).fetchone()
        return tuple(row)
    finally:
        connection.close()


def _run_version(database_path: Path) -> int:
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute("SELECT version FROM runs WHERE id = 'run-1';").fetchone()
        return int(row[0])
    finally:
        connection.close()


def _duplicate_risk(
    decision: str,
    *,
    matched_ids: tuple[str, ...] = (),
    freshness: str = "EVIDENCE_ONLY",
) -> dict[str, object]:
    return {
        "duplicate": {
            "decision": decision,
            "matched_resource_ids": list(matched_ids),
            "reason_codes": [
                "NO_MATCHING_INCOMPLETE_TASK"
                if decision == "NOT_DUPLICATE"
                else "TITLE_EXACT_DATE_EXACT"
                if decision == "CLEAR_DUPLICATE"
                else "TITLE_EXACT_DATE_DIFFERENT"
            ],
            "checked_at_ms": 1000,
            "freshness": freshness,
        }
    }


class _TaskDuplicatePreflightGateway:
    def __init__(
        self,
        *,
        database_path: Path,
        tasks: tuple[ResourceSnapshot, ...] = (),
        error: Exception | None = None,
    ) -> None:
        self.database_path = database_path
        self.tasks = tasks
        self.error = error
        self.calls = 0

    def list_tasks(
        self,
        *,
        task_list_id: str,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        del task_list_id, page_token, page_size
        _assert_can_open_sqlite_write_transaction(self.database_path)
        self.calls += 1
        if self.error is not None:
            raise self.error
        return ResourcePage(items=self.tasks, next_page_token=None)


def _duplicate_task(resource_id: str, *, title: str) -> ResourceSnapshot:
    return ResourceSnapshot(
        fixture_snapshot_id=resource_id,
        resource_type=ResourceType.TASK,
        resource_id=resource_id,
        parent_id="task-list-default",
        related_resource_ids=("task-list-default",),
        version="1",
        recovery_fingerprint=None,
        payload={"title": title, "status": "needsAction"},
    )


def _approve_preflight_action(
    *, write_database: Path, clock: FakeClock, suffix: str, risk: dict[str, object]
) -> None:
    _prepare_write_plan(
        write_database=write_database,
        clock=clock,
        suffix=suffix,
        risk=risk,
    )
    response = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        ApproveWriteActionCommand(
            command_id=f"approve-{suffix}",
            request_hash="fe" * 32,
            action_id=f"action-{suffix}",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id=f"approval-{suffix}",
            idempotency_key="ff" * 32,
            duplicate_acknowledged=True,
        )
    )
    assert response.applied is True


class _FeasibilityPreflightGateway:
    def __init__(
        self, *, busy_event: ResourceSnapshot | None = None, error: Exception | None = None
    ) -> None:
        self.busy_event = busy_event
        self.error = error

    def list_calendar_events(self, **kwargs: object) -> ResourcePage:
        if self.error is not None and str(kwargs.get("time_max", "")).endswith("18:00:00+09:00"):
            raise self.error
        is_horizon = str(kwargs.get("time_max", "")).endswith("18:00:00+09:00")
        items = (self.busy_event,) if is_horizon and self.busy_event is not None else ()
        return ResourcePage(items=items, next_page_token=None)

    def query_freebusy(
        self, *, calendar_ids: tuple[str, ...], time_range: TimeRange
    ) -> tuple[FreeBusyCalendar, ...]:
        del time_range
        return (FreeBusyCalendar(calendar_id=calendar_ids[0], intervals=()),)


def _feasibility_risk(decision: str, *, best_minutes: int) -> dict[str, object]:
    return {
        "calendar_conflict": {
            "decision": "NO_CONFLICT",
            "matched_resource_ids": [],
            "reason_codes": ["NO_CONFLICT"],
            "checked_at_ms": 1000,
            "freshness": "EVIDENCE_ONLY",
        },
        "feasibility_input": {
            "business_deadline": "1970-01-01",
            "business_deadline_source": "USER",
            "required_duration_minutes": 120,
            "duration_source": "EXPLICIT_ESTIMATE",
        },
        "feasibility": {
            "decision": decision,
            "reason_codes": [
                "CLEAN_SLOT_AVAILABLE" if decision == "FEASIBLE" else "NO_CONTIGUOUS_SLOT"
            ],
            "business_deadline": "1970-01-01",
            "derived_cutoff": "1970-01-01T18:00:00+09:00",
            "required_duration_minutes": 120,
            "best_clean_slot_minutes": best_minutes,
            "best_warning_slot_minutes": best_minutes,
            "checked_at_ms": 1000,
            "freshness": "EVIDENCE_ONLY",
        },
    }


def _prepare_calendar_feasibility_action(
    *, write_database: Path, clock: FakeClock, suffix: str, risk: dict[str, object]
) -> WriteActionResponse:
    payload = {
        "summary": "work block",
        "start": "1970-01-01T09:00:00+09:00",
        "end": "1970-01-01T10:00:00+09:00",
    }
    save = SaveWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database), now_ms=clock.now_ms
    )
    publish = PublishWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database), now_ms=clock.now_ms
    )
    save(
        SaveWritePlanCommand(
            command_id=f"save-{suffix}",
            request_hash="a1" * 32,
            plan_id=f"plan-{suffix}",
            run_id="run-1",
            revision_no=1,
            summary_text="calendar feasibility",
            expected_run_version=0,
            actions=(
                WriteActionDraft(
                    action_id=f"action-{suffix}",
                    position=1,
                    tool_name="calendar_create_event",
                    arguments={"calendar_id": "primary", "payload": payload},
                    expected={
                        "resource_type": "calendar_event",
                        "resource_id": None,
                        "payload": payload,
                    },
                    evidence_ids=(f"evidence-{suffix}",),
                    risk=risk,
                ),
            ),
            evidence=(
                WriteEvidenceDraft(
                    evidence_id=f"evidence-{suffix}",
                    origin_type=EvidenceOriginType.DERIVED,
                    kind="USER_REQUEST",
                    excerpt="calendar feasibility",
                ),
            ),
        )
    )
    publish(
        PublishWritePlanCommand(
            command_id=f"publish-{suffix}",
            request_hash="a2" * 32,
            plan_id=f"plan-{suffix}",
            run_id="run-1",
            expected_run_version=0,
        )
    )
    approved = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database), now_ms=clock.now_ms
    )(
        ApproveWriteActionCommand(
            command_id=f"approve-{suffix}",
            request_hash="a3" * 32,
            action_id=f"action-{suffix}",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id=f"approval-{suffix}",
            idempotency_key="a4" * 32,
        )
    )
    return approved


def _prepare_write_plan(
    *,
    write_database: Path,
    clock: FakeClock,
    suffix: str,
    run_id: str = "run-1",
    risk: dict[str, object] | None = None,
) -> None:
    if run_id != "run-1":
        connection = connect_sqlite(write_database)
        try:
            connection.execute(
                """
                INSERT INTO conversations (id, account_id, title, created_at_ms, updated_at_ms)
                VALUES (?, 'account-1', ?, 1, 1);
                """,
                (f"conversation-{suffix}", f"Conversation {suffix}"),
            )
            connection.execute(
                """
                INSERT INTO runs (
                    id, conversation_id, entry_mode, status, langgraph_thread_id,
                    requested_mode, budget_json, version, started_at_ms
                )
                VALUES (?, ?, 'AGENT_SEARCH', 'PLANNING', ?, 'AUTO', '{}', 0, 100);
                """,
                (run_id, f"conversation-{suffix}", f"thread-{suffix}"),
            )
        finally:
            connection.close()

    save_service = SaveWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    publish_service = PublishWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    payload = {
        "resource_id": f"task-{suffix}",
        "title": f"title-{suffix}",
        "status": "needsAction",
    }
    expected = _expected_task_projection(
        resource_id=f"task-{suffix}",
        payload=payload,
        version="1",
    )
    save_service(
        SaveWritePlanCommand(
            command_id=f"save-{suffix}",
            request_hash=("d" + suffix[0]) * 32,
            plan_id=f"plan-{suffix}",
            run_id=run_id,
            revision_no=1,
            summary_text="prepare write plan",
            expected_run_version=0,
            actions=(
                WriteActionDraft(
                    action_id=f"action-{suffix}",
                    position=1,
                    tool_name="tasks_create_task",
                    arguments={"task_list_id": "task-list-default", "payload": payload},
                    expected=expected,
                    evidence_ids=(f"evidence-{suffix}",),
                    risk={} if risk is None else risk,
                ),
            ),
            evidence=(
                WriteEvidenceDraft(
                    evidence_id=f"evidence-{suffix}",
                    origin_type=EvidenceOriginType.DERIVED,
                    kind="USER_REQUEST",
                    excerpt="prepare write plan",
                ),
            ),
        )
    )
    publish_service(
        PublishWritePlanCommand(
            command_id=f"publish-{suffix}",
            request_hash=("e" + suffix[0]) * 32,
            plan_id=f"plan-{suffix}",
            run_id=run_id,
            expected_run_version=0,
        )
    )


def _prepare_claimed_action(
    *,
    write_database: Path,
    clock: FakeClock,
    suffix: str,
    run_id: str = "run-1",
) -> WriteActionResponse:
    _prepare_write_plan(write_database=write_database, clock=clock, suffix=suffix, run_id=run_id)
    approve_service = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    claim_service = ClaimWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )
    approve_service(
        ApproveWriteActionCommand(
            command_id=f"approve-{suffix}",
            request_hash=("f" + suffix[0]) * 32,
            action_id=f"action-{suffix}",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id=f"approval-{suffix}",
            idempotency_key=(f"approve-{suffix}".encode().hex())[:64].ljust(64, "0"),
        )
    )
    return claim_service(
        ClaimWriteActionCommand(
            command_id=f"claim-{suffix}",
            request_hash=("g" + suffix[0]) * 32,
            action_id=f"action-{suffix}",
            expected_version=1,
            source_snapshot={},
            attempt_id=f"attempt-{suffix}",
            nonce=f"nonce-{suffix}",
        )
    )


def _prepare_mismatch(*, write_database: Path, gateway: FakeGoogleGateway, suffix: str) -> int:
    clock = FakeClock(1000)
    claimed = _prepare_claimed_action(
        write_database=write_database,
        clock=clock,
        suffix=suffix,
    )
    execute_service = ExecuteWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        gateway=gateway,
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )
    store_service = StoreWriteActionSuccessService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    verify_service = VerifyWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        gateway=gateway,
    )
    executed = execute_service(
        action_id=f"action-{suffix}",
        claim_token=claimed.claim_token or "",
    )
    store_service(
        StoreWriteActionSuccessCommand(
            command_id=f"store-{suffix}",
            request_hash="c8" * 32,
            action_id=f"action-{suffix}",
            attempt_id=f"attempt-{suffix}",
            expected_action_version=2,
            expected_attempt_version=0,
            snapshot=executed.snapshot,
        )
    )
    gateway.queue_fault(
        operation="get_task",
        fault=GoogleGatewayFault(GoogleGatewayFaultKind.VERIFICATION_MISMATCH),
    )
    verify_service(
        VerifyWriteActionCommand(
            command_id=f"verify-{suffix}",
            request_hash="c9" * 32,
            action_id=f"action-{suffix}",
            attempt_id=f"attempt-{suffix}",
            expected_action_version=3,
            verification_id=f"verification-{suffix}",
        )
    )
    connection = connect_sqlite(write_database)
    try:
        row = connection.execute("SELECT version FROM runs WHERE id = 'run-1';").fetchone()
        return int(row[0])
    finally:
        connection.close()


def _prepare_effect_write_plan(
    *,
    write_database: Path,
    clock: FakeClock,
    suffix: str,
    tool_name: str,
    arguments: dict[str, object],
    expected: dict[str, object],
    target_resource_ref_id: str | None = None,
    evidence_count: int = 1,
) -> None:
    save_service = SaveWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    publish_service = PublishWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    evidence_ids = tuple(f"evidence-{suffix}-{index}" for index in range(evidence_count))
    saved = save_service(
        SaveWritePlanCommand(
            command_id=f"save-{suffix}",
            request_hash="a0" * 32,
            plan_id=f"plan-{suffix}",
            run_id="run-1",
            revision_no=1,
            summary_text=f"prepare {tool_name} effect",
            expected_run_version=0,
            actions=(
                WriteActionDraft(
                    action_id=f"action-{suffix}",
                    position=1,
                    tool_name=tool_name,
                    arguments=arguments,
                    expected=expected,
                    evidence_ids=evidence_ids,
                    target_resource_ref_id=target_resource_ref_id,
                ),
            ),
            evidence=tuple(
                WriteEvidenceDraft(
                    evidence_id=evidence_id,
                    origin_type=EvidenceOriginType.DERIVED,
                    kind="USER_REQUEST",
                    excerpt=f"prepare {tool_name} effect",
                )
                for evidence_id in evidence_ids
            ),
        )
    )
    assert saved.applied is True
    published = publish_service(
        PublishWritePlanCommand(
            command_id=f"publish-{suffix}",
            request_hash="b0" * 32,
            plan_id=f"plan-{suffix}",
            run_id="run-1",
            expected_run_version=saved.run_version,
        )
    )
    assert published.applied is True


def _approve_effect_action(
    *, write_database: Path, clock: FakeClock, suffix: str
) -> WriteActionResponse:
    return ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        ApproveWriteActionCommand(
            command_id=f"approve-{suffix}",
            request_hash="c0" * 32,
            action_id=f"action-{suffix}",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id=f"approval-{suffix}",
            idempotency_key=(f"approve-{suffix}".encode().hex())[:64].ljust(64, "0"),
        )
    )


def _claim_effect_action(
    *,
    write_database: Path,
    clock: FakeClock,
    suffix: str,
    expected_version: int,
) -> WriteActionResponse:
    return ClaimWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )(
        ClaimWriteActionCommand(
            command_id=f"claim-{suffix}",
            request_hash="d0" * 32,
            action_id=f"action-{suffix}",
            expected_version=expected_version,
            source_snapshot={},
            attempt_id=f"attempt-{suffix}",
            nonce=f"nonce-{suffix}",
        )
    )


def _mark_effect_unknown(
    *,
    write_database: Path,
    clock: FakeClock,
    suffix: str,
    error: GoogleWorkspaceGatewayError,
) -> WriteActionResponse:
    return MarkWriteActionUnknownResultService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        MarkWriteActionUnknownResultCommand(
            command_id=f"unknown-{suffix}",
            request_hash="e1" * 32,
            action_id=f"action-{suffix}",
            attempt_id=f"attempt-{suffix}",
            expected_action_version=2,
            expected_attempt_version=0,
            error_code=error.code.value,
            error_detail=str(error),
        )
    )


def _insert_calendar_event_reference(write_database: Path, *, version: str = "7") -> None:
    connection = connect_sqlite(write_database)
    try:
        connection.execute(
            """
            INSERT INTO resource_refs (
                id, run_id, source, resource_type, resource_id, parent_resource_id,
                canonical_url, title, event_time_ms, version_token, metadata_json, captured_at_ms
            ) VALUES (
                'resource-event-focus', 'run-1', 'CALENDAR', 'EVENT',
                'event-focus', 'calendar-primary', NULL, 'Focus block', NULL, ?, ?, 1000
            );
            """,
            (
                version,
                '{"end":"2026-11-01T09:00:00-07:00","event_kind":"focusTime",'
                '"start":"2026-11-01T08:00:00-07:00","status":"confirmed",'
                '"title":"Focus block","transparency":"busy"}',
            ),
        )
    finally:
        connection.close()


def _insert_task_delete_reference(write_database: Path, *, version: str = "4") -> None:
    connection = connect_sqlite(write_database)
    try:
        connection.execute(
            """
            INSERT INTO resource_refs (
                id, run_id, source, resource_type, resource_id, parent_resource_id,
                canonical_url, title, event_time_ms, version_token, metadata_json, captured_at_ms
            ) VALUES (
                'resource-task-followup', 'run-1', 'TASKS', 'TASK',
                'task-followup', 'task-list-default', NULL, 'Reply to project sync',
                NULL, ?, ?, 1000
            );
            """,
            (
                version,
                '{"due":"2026-08-07","notes":"Reference the Thursday summary.",'
                '"status":"needsAction","title":"Reply to project sync"}',
            ),
        )
    finally:
        connection.close()


def _prepare_update_claimed_action(
    *,
    write_database: Path,
    clock: FakeClock,
    suffix: str,
) -> WriteActionResponse:
    source_payload = {
        "title": "Reply to project sync",
        "notes": "Reference the Thursday summary.",
        "due": "2026-08-07",
        "status": "needsAction",
    }
    source_snapshot = _expected_task_projection(
        resource_id="task-followup",
        payload=source_payload,
        version="4",
    )
    connection = connect_sqlite(write_database)
    try:
        connection.execute(
            """
            INSERT INTO resource_refs (
                id, run_id, source, resource_type, resource_id, parent_resource_id,
                canonical_url, title, event_time_ms, version_token, metadata_json, captured_at_ms
            )
            VALUES (
                ?, 'run-1', 'TASKS', 'TASK', 'task-followup', 'task-list-default',
                NULL, 'Reply to project sync', NULL, '4', ?, 1000
            );
            """,
            (
                "resource-ref-run-1-task-task-followup",
                (
                    '{"due":"2026-08-07","notes":"Reference the Thursday summary.",'
                    '"status":"needsAction","title":"Reply to project sync"}'
                ),
            ),
        )
    finally:
        connection.close()

    save_service = SaveWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    publish_service = PublishWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    approve_service = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )
    claim_service = ClaimWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        signing_secret="phase-e-secret",
        service_instance_id="write-svc-1",
    )
    updated_payload = dict(source_payload)
    updated_payload["title"] = "Updated from retry preparation"
    save_service(
        SaveWritePlanCommand(
            command_id=f"save-{suffix}",
            request_hash="y1" * 32,
            plan_id=f"plan-{suffix}",
            run_id="run-1",
            revision_no=1,
            summary_text="prepare update plan",
            expected_run_version=0,
            actions=(
                WriteActionDraft(
                    action_id=f"action-{suffix}",
                    position=1,
                    tool_name="tasks_update_task",
                    arguments={
                        "task_list_id": "task-list-default",
                        "task_id": "task-followup",
                        "payload": {"title": "Updated from retry preparation"},
                    },
                    expected=_expected_task_projection(
                        resource_id="task-followup",
                        payload=updated_payload,
                        version="5",
                    ),
                    evidence_ids=(f"evidence-{suffix}",),
                    target_resource_ref_id="resource-ref-run-1-task-task-followup",
                ),
            ),
            evidence=(
                WriteEvidenceDraft(
                    evidence_id=f"evidence-{suffix}",
                    origin_type=EvidenceOriginType.DERIVED,
                    kind="USER_REQUEST",
                    excerpt="prepare update plan",
                ),
            ),
        )
    )
    publish_service(
        PublishWritePlanCommand(
            command_id=f"publish-{suffix}",
            request_hash="y2" * 32,
            plan_id=f"plan-{suffix}",
            run_id="run-1",
            expected_run_version=0,
        )
    )
    approve_service(
        ApproveWriteActionCommand(
            command_id=f"approve-{suffix}",
            request_hash="y3" * 32,
            action_id=f"action-{suffix}",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot=source_snapshot,
            approval_id=f"approval-{suffix}",
            idempotency_key="y4" * 32,
        )
    )
    return claim_service(
        ClaimWriteActionCommand(
            command_id=f"claim-{suffix}",
            request_hash="y5" * 32,
            action_id=f"action-{suffix}",
            expected_version=1,
            source_snapshot=source_snapshot,
            attempt_id=f"attempt-{suffix}",
            nonce=f"nonce-{suffix}",
        )
    )


def _expected_task_projection(
    *,
    resource_id: str,
    payload: Mapping[str, object],
    version: str,
) -> dict[str, object]:
    return {
        "resource_type": "task",
        "resource_id": resource_id,
        "parent_id": "task-list-default",
        "version": version,
        "payload": dict(payload),
    }
