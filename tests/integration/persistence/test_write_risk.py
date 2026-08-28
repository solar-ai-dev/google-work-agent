"""Write reauth and persisted risk integration tests."""

# ruff: noqa: F401

from __future__ import annotations

from json import loads as _loads
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.connectors.google.workspace.composition import (
    GOOGLE_WORKSPACE_CONNECTOR_ID,
)
from google_work_agent.adapters.system.sqlite_checkpoint import SqliteCheckpointAdapter
from google_work_agent.ports.system.contracts.workflow_binding import WorkflowBindingV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    MainControlResumeTargetV2,
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
        now_ms=clock.now_ms,
    )
    response = request_service(
        RequireWriteReauthCommand(
            command_id="reauth-1",
            request_hash="z1" * 32,
            run_id="run-1",
            action_id="action-reauth",
            safe_error_code=GoogleWorkspaceErrorCode.AUTH_EXPIRED.value,
        )
    )
    assert response.applied is True
    assert response.run_status == "REAUTH_REQUIRED"


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
        now_ms=clock.now_ms,
    )
    response = request_service(
        RequireWriteReauthCommand(
            command_id="reauth-mcp-1",
            request_hash="z2" * 32,
            run_id="run-1",
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
