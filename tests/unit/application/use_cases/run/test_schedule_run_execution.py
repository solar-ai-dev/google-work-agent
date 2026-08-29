from __future__ import annotations

from pathlib import Path

from google_work_agent.adapters.langgraph.registry.node_registry import NodeRegistry
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    ResumeTargetRegistry,
)
from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    CheckpointEffectiveBindingResolver,
    ScheduleRunExecutionCommand,
    ScheduleRunExecutionHandler,
)
from google_work_agent.ports.system.contracts.checkpoint import GraphCheckpointEnvelopeV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    MainControlResumeTargetV2,
    RunExecutionAcceptedV1,
    RunExecutionRefV1,
    WorkflowExecutionAdmissionV1,
    WorkflowExecutionBindingV1,
    WorkflowExecutionSubmissionV2,
    WorkflowHandoffStageV1,
    WorkflowHandoffV1,
)


class _ExecutionPort:
    def __init__(self, *, accepted: bool = True) -> None:
        self.submissions: list[WorkflowExecutionSubmissionV2] = []
        self.accepted = accepted

    def submit(self, submission: WorkflowExecutionSubmissionV2) -> RunExecutionAcceptedV1:
        self.submissions.append(submission)
        return RunExecutionAcceptedV1(
            schema_version=1,
            accepted=self.accepted,
            reason_code="ACCEPTED" if self.accepted else "ALREADY_RUNNING",
        )

    def begin_shutdown(self) -> None: ...
    def await_drained(self, deadline_ms: int) -> bool:
        return True


def test_claims_durable_admission_before_submit_and_replays_same_admission(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    with factory() as unit_of_work:
        unit_of_work.workflow_handoffs.stage_pending(_stage())
        unit_of_work.commit()
    execution = _ExecutionPort()
    handler = ScheduleRunExecutionHandler(
        unit_of_work_factory=factory,
        workflow_execution=execution,
        id_factory=lambda: "admission-1",
    )

    first = handler(ScheduleRunExecutionCommand("h-1"))
    replay = handler(ScheduleRunExecutionCommand("h-1"))

    assert first.accepted and replay.accepted
    assert [item.admission.admission_id for item in execution.submissions] == [
        "admission-1",
        "admission-1",
    ]
    with factory() as unit_of_work:
        persisted = unit_of_work.workflow_handoffs.get("h-1")
    assert persisted is not None
    assert persisted.status == "DISPATCHED"
    assert persisted.execution_admission == execution.submissions[0].admission


def test_non_accepted_submit_releases_equal_epoch_admission(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    with factory() as unit_of_work:
        unit_of_work.workflow_handoffs.stage_pending(_stage())
        unit_of_work.commit()
    handler = ScheduleRunExecutionHandler(
        unit_of_work_factory=factory,
        workflow_execution=_ExecutionPort(accepted=False),
        id_factory=lambda: "admission-1",
    )

    result = handler(ScheduleRunExecutionCommand("h-1"))

    assert not result.accepted
    with factory() as unit_of_work:
        persisted = unit_of_work.workflow_handoffs.get("h-1")
    assert persisted is not None
    assert persisted.status == "PENDING"
    assert persisted.execution_admission is None
    assert persisted.last_submit_reason == "ALREADY_RUNNING"


def test_reused_admission_with_stale_binding_is_released_not_blindly_resubmitted(
    tmp_path: Path,
) -> None:
    database_path = _database(tmp_path)
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    with factory() as unit_of_work:
        handoff = unit_of_work.workflow_handoffs.stage_pending(_stage())
        claimed = unit_of_work.workflow_handoffs.claim_execution_admission(
            handoff.handoff_id,
            handoff.version,
            _admission_for(handoff),
        )
        unit_of_work.commit()
    assert claimed.status == "DISPATCHED"

    class _StaleBindingResolver:
        def __call__(
            self, handoff: WorkflowHandoffV1, submission_kind: str
        ) -> WorkflowExecutionBindingV1:
            return WorkflowExecutionBindingV1(
                schema_version=1,
                execution_kind="START",
                run_id="r-1",
                langgraph_thread_id="t-1",
                graph_profile="SIX_ROLE_BASELINE",
                graph_version="v2",
                requested_mode="AUTO",
                checkpoint_id=None,
                checkpoint_generation=0,
                resume_target=None,
            )

    execution = _ExecutionPort()
    handler = ScheduleRunExecutionHandler(
        unit_of_work_factory=factory,
        workflow_execution=execution,
        id_factory=lambda: "admission-2",
        effective_binding_resolver=_StaleBindingResolver(),
    )

    result = handler(ScheduleRunExecutionCommand("h-1"))

    assert not result.accepted
    assert result.reason_code == "BINDING_MISMATCH"
    assert execution.submissions == []
    with factory() as unit_of_work:
        persisted = unit_of_work.workflow_handoffs.get("h-1")
    assert persisted is not None
    assert persisted.status == "BLOCKED_BINDING"
    assert persisted.execution_admission is None


def test_stale_admission_is_retired_before_preempting_authority_return(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    with factory() as unit_of_work:
        handoff = unit_of_work.workflow_handoffs.stage_pending(_stage())
        unit_of_work.workflow_handoffs.claim_execution_admission(
            handoff.handoff_id, handoff.version, _admission_for(handoff)
        )
        unit_of_work.commit()
    with connect_sqlite(database_path) as connection:
        connection.execute("UPDATE runs SET status='RECOVERY_REQUIRED', version=1 WHERE id='r-1';")
        connection.commit()
    execution = _ExecutionPort()
    handler = ScheduleRunExecutionHandler(
        unit_of_work_factory=factory, workflow_execution=execution, id_factory=lambda: "admission-2"
    )

    result = handler(ScheduleRunExecutionCommand("h-1"))

    assert not result.accepted
    assert result.reason_code == "BINDING_MISMATCH"
    assert execution.submissions == []
    with factory() as unit_of_work:
        persisted = unit_of_work.workflow_handoffs.get("h-1")
    assert persisted is not None
    assert persisted.status == "SUPERSEDED"
    assert persisted.execution_admission is None


def test_normal_schedule_rejects_each_fresh_preempting_status_without_submit(
    tmp_path: Path,
) -> None:
    for status in ("REAUTH_REQUIRED", "RECOVERY_REQUIRED", "CANCEL_REQUESTED"):
        status_path = tmp_path / status
        status_path.mkdir()
        database_path = _database(status_path)
        factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
        with factory() as unit_of_work:
            unit_of_work.workflow_handoffs.stage_pending(_stage())
            unit_of_work.commit()
        with connect_sqlite(database_path) as connection:
            connection.execute("UPDATE runs SET status=? WHERE id='r-1';", (status,))
            connection.commit()
        execution = _ExecutionPort()
        handler = ScheduleRunExecutionHandler(
            unit_of_work_factory=factory,
            workflow_execution=execution,
            id_factory=lambda: "admission-1",
        )

        result = handler(ScheduleRunExecutionCommand("h-1"))

        assert not result.accepted
        assert result.reason_code == "BINDING_MISMATCH"
        assert execution.submissions == []


def test_cancel_requested_allows_only_its_cancel_resolution_handoff(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    target = MainControlResumeTargetV2(
        "MAIN_CONTROL", "CANCEL_RESOLUTION", "SIX_ROLE_BASELINE", "v1"
    )
    with connect_sqlite(database_path) as connection:
        connection.execute("UPDATE runs SET status='CANCEL_REQUESTED' WHERE id='r-1';")
        connection.commit()
    with factory() as unit_of_work:
        unit_of_work.workflow_handoffs.stage_pending(
            WorkflowHandoffStageV1(
                1,
                "h-cancel",
                "cmd-cancel",
                RunExecutionRefV1(
                    1, "RESUME", "r-1", "t-1", "SIX_ROLE_BASELINE", "v1", "AUTO", target
                ),
                "cp-1",
                1,
                "NONE",
                None,
                None,
            )
        )
        unit_of_work.commit()
    execution = _ExecutionPort()

    result = ScheduleRunExecutionHandler(
        unit_of_work_factory=factory,
        workflow_execution=execution,
        id_factory=lambda: "admission-cancel",
    )(ScheduleRunExecutionCommand("h-cancel"))

    assert result.accepted
    assert len(execution.submissions) == 1


def test_consumed_recovery_resolves_latest_active_lineage_checkpoint() -> None:
    target = MainControlResumeTargetV2("MAIN_CONTROL", "PREFLIGHT", "SIX_ROLE_BASELINE", "v1")
    checkpoint = GraphCheckpointEnvelopeV1(
        1,
        "cp-latest",
        4,
        "r-1",
        "t-1",
        "SIX_ROLE_BASELINE",
        "v1",
        "MAIN_CONTROL",
        target,
        "h-1",
        None,
        "h-1",
        1,
        (),
        10,
        b"opaque",
    )

    class _CheckpointPort:
        def load_same_run_checkpoint(self, run_id: str, thread_id: str):
            assert (run_id, thread_id) == ("r-1", "t-1")
            return checkpoint

    resume_target_registry = ResumeTargetRegistry(
        node_registry=NodeRegistry(graph_version="v1"), graph_version="v1"
    )
    resolver = CheckpointEffectiveBindingResolver(
        _CheckpointPort(),  # type: ignore[arg-type]
        resume_target_registry,
    )
    binding = resolver(_consumed_handoff(), "CONSUMED_CONTINUATION_RECOVERY")

    assert binding is not None
    assert binding.execution_kind == "RESUME"
    assert binding.checkpoint_id == "cp-latest"
    assert binding.checkpoint_generation == 4
    assert binding.resume_target == target


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "schedule.db"
    with connect_sqlite(path) as connection:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('a-1', 'u@example.com', NULL, 1, NULL);"
        )
        connection.execute("INSERT INTO conversations VALUES ('c-1', 'a-1', 'Test', 1, 1);")
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, actual_runtime, budget_json, version, started_at_ms, finished_at_ms
            ) VALUES ('r-1', 'c-1', 'AGENT_SEARCH', 'CREATED', 't-1',
                      'AUTO', NULL, '{}', 0, 1, NULL);
            """
        )
        connection.commit()
    return path


def _stage() -> WorkflowHandoffStageV1:
    return WorkflowHandoffStageV1(
        schema_version=1,
        handoff_id="h-1",
        trigger_command_id="cmd-1",
        execution=RunExecutionRefV1(
            1, "START", "r-1", "t-1", "SIX_ROLE_BASELINE", "v1", "AUTO", None
        ),
        checkpoint_id=None,
        checkpoint_generation=0,
        control_kind="NONE",
        control=None,
        control_payload_hash=None,
    )


def _admission_for(handoff: WorkflowHandoffV1) -> WorkflowExecutionAdmissionV1:
    return WorkflowExecutionAdmissionV1(
        schema_version=1,
        admission_id="admission-1",
        handoff_id=handoff.handoff_id,
        handoff_run_sequence=handoff.run_sequence,
        submission_kind="NORMAL_HANDOFF",
        effective_binding=WorkflowExecutionBindingV1(
            schema_version=1,
            execution_kind="START",
            run_id="r-1",
            langgraph_thread_id="t-1",
            graph_profile="SIX_ROLE_BASELINE",
            graph_version="v1",
            requested_mode="AUTO",
            checkpoint_id=None,
            checkpoint_generation=0,
            resume_target=None,
        ),
        expected_run_version=0,
    )


def _consumed_handoff() -> WorkflowHandoffV1:
    return WorkflowHandoffV1(
        1,
        "h-1",
        "cmd-1",
        RunExecutionRefV1(1, "START", "r-1", "t-1", "SIX_ROLE_BASELINE", "v1", "AUTO", None),
        None,
        0,
        1,
        "NONE",
        None,
        None,
        "CONSUMED",
        None,
        None,
        "cp-initial",
        1,
        2,
    )
