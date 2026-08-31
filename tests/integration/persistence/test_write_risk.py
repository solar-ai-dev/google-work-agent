"""Write reauth and persisted risk integration tests."""

# ruff: noqa: F401

from __future__ import annotations

from dataclasses import replace
from json import loads as _loads
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.connectors.google.workspace.composition import (
    GOOGLE_WORKSPACE_CONNECTOR_ID,
)
from google_work_agent.adapters.langgraph.registry.node_registry import NodeRegistry
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    ResumeTargetRegistry,
)
from google_work_agent.adapters.system.sqlite_checkpoint import SqliteCheckpointAdapter
from google_work_agent.application.use_cases.run.request_cancel import (
    RequestCancelCommand,
    RequestCancelHandler,
)
from google_work_agent.application.use_cases.run.resume_after_reauth import (
    ResumeAfterReauthCommand,
    ResumeAfterReauthHandler,
)
from google_work_agent.ports.system.contracts.workflow_binding import WorkflowBindingV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    MainControlResumeTargetV2,
    RunExecutionAcceptedV1,
    WorkflowExecutionAdmissionV1,
    WorkflowExecutionBindingV1,
)
from tests.integration.persistence.test_write_actions import (
    EvidenceOriginType,
    FakeClockPort,
    FakeGoogleGateway,
    GoogleWorkspaceErrorCode,
    InvariantViolationError,
    Path,
    RequireReauthHandler,
    RequireWriteReauthCommand,
    SaveWritePlanCommand,
    SaveWritePlanService,
    SnapshotReader,
    WriteActionDraft,
    WriteEvidenceDraft,
    _prepare_write_plan,
    connect_sqlite,
    pytest,
    sqlite_unit_of_work_factory,
)
from tests.support.fakes import DeterministicUUID

pytest_plugins = ("tests.integration.persistence.test_write_actions",)


class _CheckpointState(TypedDict):
    value: int


def _register_preflight_resume_target(write_database: Path, clock: FakeClockPort) -> None:
    checkpoint = SqliteCheckpointAdapter(write_database, now_ms=clock.now_ms)
    checkpoint.create_workflow_binding(
        WorkflowBindingV1(
            1,
            "workflow-1",
            "run-1",
            "thread-1",
            "SIX_ROLE_BASELINE",
            "v1",
            "AUTO",
            clock.now_ms(),
        )
    )
    checkpoint.flush()
    target = MainControlResumeTargetV2("MAIN_CONTROL", "PREFLIGHT", "SIX_ROLE_BASELINE", "v1")
    admission = WorkflowExecutionAdmissionV1(
        1,
        "admission-1",
        "handoff-1",
        1,
        "NORMAL_HANDOFF",
        WorkflowExecutionBindingV1(
            1,
            "START",
            "run-1",
            "thread-1",
            "SIX_ROLE_BASELINE",
            "v1",
            "AUTO",
            None,
            0,
            None,
        ),
        0,
    )
    builder = StateGraph(_CheckpointState)
    builder.add_node("owner", lambda state: state)
    builder.add_edge(START, "owner")
    builder.add_edge("owner", END)
    graph = builder.compile(checkpointer=checkpoint)
    with checkpoint.execution_scope(
        admission,
        applied_handoff_id="handoff-1",
        owner_scope="MAIN_CONTROL",
        resume_target=target,
    ):
        graph.invoke(
            {"value": 0},
            config={"configurable": {"thread_id": "thread-1"}},
            interrupt_before=["owner"],
        )
    checkpoint.flush()
    checkpoint.close()


def test_reauth_core_command_marks_run_without_langgraph_dependency(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    del fixture_gateway
    clock = FakeClockPort(1000)
    _prepare_write_plan(write_database=write_database, clock=clock, suffix="reauth")
    _register_preflight_resume_target(write_database, clock)
    request_service = RequireReauthHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        checkpoint_port=SqliteCheckpointAdapter(write_database, now_ms=clock.now_ms),
        now_ms=clock.now_ms,
    )
    response = request_service(
        RequireWriteReauthCommand(
            command_id="reauth-1",
            request_hash="z1" * 32,
            run_id="run-1",
            expected_run_version=1,
            action_id="action-reauth",
            safe_error_code=GoogleWorkspaceErrorCode.AUTH_EXPIRED.value,
        )
    )
    assert response.applied is True
    assert response.run_status == "REAUTH_REQUIRED"
    checkpoint = SqliteCheckpointAdapter(write_database, now_ms=clock.now_ms)
    try:
        envelope = checkpoint.load_same_run_checkpoint("run-1", "thread-1")
        assert envelope is not None
        assert envelope.pre_reauth_status is not None
        assert envelope.pre_reauth_status.value == "WAITING_APPROVAL"
    finally:
        checkpoint.close()


def test_reauth_rejects_stale_run_version_without_persisting_prior_status(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    del fixture_gateway
    clock = FakeClockPort(1000)
    _prepare_write_plan(write_database=write_database, clock=clock, suffix="reauth-stale")
    _register_preflight_resume_target(write_database, clock)
    response = RequireReauthHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        checkpoint_port=SqliteCheckpointAdapter(write_database, now_ms=clock.now_ms),
        now_ms=clock.now_ms,
    )(
        RequireWriteReauthCommand(
            command_id="reauth-stale-1",
            request_hash="z3" * 32,
            run_id="run-1",
            expected_run_version=0,
            action_id="action-reauth-stale",
            safe_error_code=GoogleWorkspaceErrorCode.AUTH_EXPIRED.value,
        )
    )

    assert not response.applied
    assert response.result_code == "VERSION_CONFLICT"
    checkpoint = SqliteCheckpointAdapter(write_database, now_ms=clock.now_ms)
    try:
        envelope = checkpoint.load_same_run_checkpoint("run-1", "thread-1")
        assert envelope is not None
        assert envelope.pre_reauth_status is None
    finally:
        checkpoint.close()


def test_reauth_command_mcp_request_id_persists_on_trace_and_audit(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    """D: an execution-phase AUTH_EXPIRED/PERMISSION_DENIED error's
    mcp_request_id (as execution_phase.py forwards it from a real
    GoogleWorkspaceGatewayError) reaches the persisted RUN_REAUTH_REQUIRED
    trace/audit rows.
    """
    del fixture_gateway
    clock = FakeClockPort(1000)
    _prepare_write_plan(write_database=write_database, clock=clock, suffix="reauth-mcp")
    _register_preflight_resume_target(write_database, clock)
    request_service = RequireReauthHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        checkpoint_port=SqliteCheckpointAdapter(write_database, now_ms=clock.now_ms),
        now_ms=clock.now_ms,
    )
    response = request_service(
        RequireWriteReauthCommand(
            command_id="reauth-mcp-1",
            request_hash="z2" * 32,
            run_id="run-1",
            expected_run_version=1,
            action_id="action-reauth-mcp",
            safe_error_code=GoogleWorkspaceErrorCode.AUTH_EXPIRED.value,
            mcp_request_id="req-simulated-42",
        )
    )
    assert response.applied is True

    connection = connect_sqlite(write_database)
    try:
        trace_row = connection.execute(
            "SELECT payload_json FROM trace_events WHERE event_type = 'RUN_REAUTH_REQUIRED';"
        ).fetchone()
        audit_row = connection.execute(
            "SELECT metadata_json FROM audit_events WHERE event_type = 'RUN_REAUTH_REQUIRED';"
        ).fetchone()
    finally:
        connection.close()

    trace_envelope = _loads(trace_row[0])
    audit_envelope = _loads(audit_row[0])
    assert trace_envelope["attributes"]["mcp_request_id"] == "req-simulated-42"
    assert audit_envelope["attributes"]["mcp_request_id"] == "req-simulated-42"


def test_cancel_requested_reauth_round_trip_restores_exact_checkpoint_status(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    del fixture_gateway
    clock = FakeClockPort(1000)
    _prepare_write_plan(write_database=write_database, clock=clock, suffix="cancel-reauth")
    _register_preflight_resume_target(write_database, clock)
    registry = ResumeTargetRegistry(NodeRegistry(graph_version="v1"), "v1")
    scheduled: list[str] = []
    cancel = RequestCancelHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        checkpoint_port=SqliteCheckpointAdapter(write_database, now_ms=clock.now_ms),
        now_ms=clock.now_ms,
        id_generator=DeterministicUUID(queued_ids=("handoff-cancel",)),
        resume_target_registry=registry,
        schedule_run_execution=lambda command: (
            scheduled.append(command.handoff_id) or RunExecutionAcceptedV1(1, True, "ACCEPTED")
        ),
    )(RequestCancelCommand("run-1", 1, "cancel-reauth", "e" * 64))
    assert cancel.current_status == "CANCEL_REQUESTED"

    checkpoint_store = SqliteCheckpointAdapter(write_database, now_ms=clock.now_ms)
    cancel_target = registry.issue_main_stage("SIX_ROLE_BASELINE", "CANCEL_RESOLUTION", "v1")
    checkpoint = checkpoint_store.load_same_run_checkpoint("run-1", "thread-1")
    assert checkpoint is not None
    checkpoint_store.store_same_run_checkpoint(
        replace(checkpoint, registered_resume_target=cancel_target)
    )
    checkpoint_store.flush()
    checkpoint_store.close()

    required = RequireReauthHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        checkpoint_port=SqliteCheckpointAdapter(write_database, now_ms=clock.now_ms),
        now_ms=clock.now_ms,
    )(
        RequireWriteReauthCommand(
            command_id="require-cancel-reauth",
            request_hash="f" * 64,
            run_id="run-1",
            expected_run_version=2,
            action_id=None,
            safe_error_code="AUTH_EXPIRED",
        )
    )
    assert required.applied and required.run_status == "REAUTH_REQUIRED"

    def authority(**_kwargs: object) -> dict[str, object]:
        store = SqliteCheckpointAdapter(write_database, now_ms=clock.now_ms)
        try:
            current = store.load_same_run_checkpoint("run-1", "thread-1")
            assert current is not None and current.pre_reauth_status is not None
            return {
                "resume_status": current.pre_reauth_status.value,
                "continuation_target": "cancel_resolution",
            }
        finally:
            store.close()

    resumed = ResumeAfterReauthHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        checkpoint_port=SqliteCheckpointAdapter(write_database, now_ms=clock.now_ms),
        now_ms=clock.now_ms,
        resolve_resume_authority=authority,
        id_generator=DeterministicUUID(queued_ids=("handoff-resume",)),
        resume_target_registry=registry,
        schedule_run_execution=lambda command: (
            scheduled.append(command.handoff_id) or RunExecutionAcceptedV1(1, True, "ACCEPTED")
        ),
    )(
        ResumeAfterReauthCommand(
            "resume-cancel-reauth",
            "1" * 64,
            "run-1",
            3,
            "REAUTH_COMPLETED",
            "1",
        ),
        request_id="request-1",
    )

    assert resumed.applied
    assert resumed.run_status == "CANCEL_REQUESTED"
    checkpoint_store = SqliteCheckpointAdapter(write_database, now_ms=clock.now_ms)
    try:
        checkpoint = checkpoint_store.load_same_run_checkpoint("run-1", "thread-1")
        assert checkpoint is not None
        assert checkpoint.pre_reauth_status is not None
        assert checkpoint.pre_reauth_status.value == "CANCEL_REQUESTED"
    finally:
        checkpoint_store.close()


def test_action_risk_defaults_to_empty_object_on_insert(write_database: Path) -> None:
    _prepare_write_plan(
        write_database=write_database,
        clock=FakeClockPort(1000),
        suffix="risk-default",
    )

    with sqlite_unit_of_work_factory(write_database)() as unit_of_work:
        action = unit_of_work.actions.get("action-risk-default")
        listed = unit_of_work.actions.list_for_plan("plan-risk-default")

    assert action is not None
    assert action.risk == {}
    assert listed[0].risk == {}
    connection = connect_sqlite(write_database)
    try:
        row = connection.execute(
            "SELECT risk_json FROM actions WHERE id = 'action-risk-default';"
        ).fetchone()
        assert str(row["risk_json"]) == "{}"
    finally:
        connection.close()


def test_action_risk_round_trips_through_repository_and_run_snapshot(
    write_database: Path,
) -> None:
    risk = {"z": ["寃쎄퀬", {"matched": True}], "a": 1}
    _prepare_write_plan(
        write_database=write_database,
        clock=FakeClockPort(1000),
        suffix="risk-roundtrip",
        risk=risk,
    )

    with sqlite_unit_of_work_factory(write_database)() as unit_of_work:
        action = unit_of_work.actions.get("action-risk-roundtrip")
        listed = unit_of_work.actions.list_for_plan("plan-risk-roundtrip")

    assert action is not None
    assert action.risk == risk
    assert listed[0].risk == risk
    snapshot = SnapshotReader(
        database_path=write_database,
        connection_factory=connect_sqlite,
        runtime_status_provider=None,  # type: ignore[arg-type]
    ).get_run_snapshot("run-1")
    assert snapshot is not None
    assert snapshot.actions[0].risk == risk

    connection = connect_sqlite(write_database)
    try:
        row = connection.execute(
            "SELECT risk_json FROM actions WHERE id = 'action-risk-roundtrip';"
        ).fetchone()
        assert str(row["risk_json"]) == '{"a":1,"z":["寃쎄퀬",{"matched":true}]}'
    finally:
        connection.close()


def test_action_risk_over_16_kib_is_rejected_before_plan_persistence(
    write_database: Path,
) -> None:
    service = SaveWritePlanService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=FakeClockPort(1000).now_ms,
    )
    with pytest.raises(InvariantViolationError, match="16 KiB"):
        service(
            SaveWritePlanCommand(
                command_id="save-risk-large",
                request_hash="91" * 32,
                plan_id="plan-risk-large",
                run_id="run-1",
                revision_no=1,
                summary_text="oversized risk",
                expected_run_version=0,
                actions=(
                    WriteActionDraft(
                        action_id="action-risk-large",
                        connector_id=GOOGLE_WORKSPACE_CONNECTOR_ID,
                        position=1,
                        tool_name="tasks_create_task",
                        arguments={
                            "task_list_id": "task-list-default",
                            "payload": {"title": "Risk limit"},
                        },
                        expected={},
                        evidence_ids=("evidence-risk-large",),
                        risk={"detail": "x" * (16 * 1024)},
                    ),
                ),
                evidence=(
                    WriteEvidenceDraft(
                        evidence_id="evidence-risk-large",
                        origin_type=EvidenceOriginType.DERIVED,
                        kind="USER_REQUEST",
                        excerpt="Create a task.",
                    ),
                ),
            )
        )

    connection = connect_sqlite(write_database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM plans;").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM actions;").fetchone()[0] == 0
    finally:
        connection.close()


def test_repository_rejects_corrupt_persisted_action_risk(write_database: Path) -> None:
    _prepare_write_plan(
        write_database=write_database,
        clock=FakeClockPort(1000),
        suffix="risk-corrupt",
    )
    connection = connect_sqlite(write_database)
    try:
        connection.execute("PRAGMA ignore_check_constraints = ON;")
        connection.execute(
            "UPDATE actions SET risk_json = 'not-json' WHERE id = 'action-risk-corrupt';"
        )
        connection.commit()
    finally:
        connection.close()

    with (
        sqlite_unit_of_work_factory(write_database)() as unit_of_work,
        pytest.raises(InvariantViolationError, match="not valid JSON"),
    ):
        unit_of_work.actions.get("action-risk-corrupt")
