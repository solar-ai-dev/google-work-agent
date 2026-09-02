from pathlib import Path
from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.adapters.system.sqlite_checkpoint import SqliteCheckpointAdapter
from google_work_agent.application.use_cases.run.begin_planning import (
    BeginPlanningCommand,
    BeginPlanningHandler,
)
from google_work_agent.application.use_cases.run.begin_retrieval import (
    BeginRetrievalCommand,
    BeginRetrievalHandler,
)
from google_work_agent.application.use_cases.run.start_analysis import (
    StartAnalysisCommand,
    StartAnalysisHandler,
)
from google_work_agent.ports.system.contracts.workflow_binding import (
    GraphProfileIdV1,
    WorkflowBindingV1,
)
from google_work_agent.ports.system.contracts.workflow_handoff import (
    AgentNodeResumeTargetV2,
    ContextAdjustmentControlV1,
    MainControlResumeTargetV2,
    MainResumeStageIdV1,
    RegisteredResumeTargetRefV2,
    WorkflowExecutionAdmissionV1,
    WorkflowExecutionBindingV1,
)


class _RetrievalState(TypedDict):
    retrieval_result: dict[str, object]


class _ResumeTargetRegistry:
    def issue_main_stage(
        self,
        graph_profile: GraphProfileIdV1,
        stage_id: MainResumeStageIdV1,
        graph_version: str,
    ) -> MainControlResumeTargetV2:
        return MainControlResumeTargetV2(
            kind="MAIN_CONTROL",
            stage_id=stage_id,
            graph_profile=graph_profile,
            graph_version=graph_version,
        )

    def validate(self, ref: RegisteredResumeTargetRefV2) -> None:
        del ref


def _database(tmp_path: Path, *, status: str, version: int = 0) -> Path:
    path = tmp_path / f"run-phase-{status.lower()}.db"
    with connect_sqlite(path) as connection:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('account-1', 'u@example.com', NULL, 1, NULL);"
        )
        connection.execute(
            "INSERT INTO conversations VALUES ('conversation-1', 'account-1', 'Test', 1, 1);"
        )
        connection.execute(
            """INSERT INTO runs (
                   id, conversation_id, entry_mode, status, langgraph_thread_id,
                   requested_mode, actual_runtime, budget_json, version,
                   started_at_ms, finished_at_ms
               ) VALUES (
                   'run-1', 'conversation-1', 'AGENT_SEARCH', ?, 'thread-1',
                   'AUTO', NULL, '{}', ?, 1, NULL
               );""",
            (status, version),
        )
        connection.commit()
    checkpoint = SqliteCheckpointAdapter(path, now_ms=lambda: 10)
    checkpoint.close()
    return path


def test_phase_handlers_apply__receipt_audit_and__run_cas_atomically(tmp_path: Path) -> None:
    path = _database(tmp_path, status="CREATED")
    factory = sqlite_unit_of_work_factory(path, now_ms=lambda: 10)
    start = StartAnalysisHandler(unit_of_work_factory=factory, now_ms=lambda: 10)
    retrieval = BeginRetrievalHandler(unit_of_work_factory=factory, now_ms=lambda: 11)
    planning = BeginPlanningHandler(
        unit_of_work_factory=factory,
        checkpoint_port=SqliteCheckpointAdapter(path, now_ms=lambda: 12),
        now_ms=lambda: 12,
        id_factory=lambda: "unused-handoff",
        resume_target_registry=_ResumeTargetRegistry(),
    )

    assert start(StartAnalysisCommand("run-1", 0, "cmd-start", "a" * 64)).applied
    assert retrieval(BeginRetrievalCommand("run-1", 1, "cmd-retrieve", "b" * 64)).applied
    assert planning(BeginPlanningCommand("run-1", 2, "cmd-plan", "c" * 64)).applied

    with connect_sqlite(path) as connection:
        run = connection.execute("SELECT status, version FROM runs WHERE id='run-1';").fetchone()
        receipts = connection.execute(
            "SELECT COUNT(*) AS count FROM command_receipts WHERE aggregate_id='run-1';"
        ).fetchone()
        events = {
            str(row["event_type"])
            for row in connection.execute(
                "SELECT event_type FROM audit_events WHERE run_id='run-1';"
            ).fetchall()
        }
    assert tuple(run) == ("PLANNING", 3)
    assert int(receipts["count"]) == 3
    assert events == {
        "RUN_ANALYSIS_STARTED",
        "RUN_RETRIEVAL_STARTED",
        "RUN_PLANNING_STARTED",
    }


def test_published_review__reentry_revokes_approval__and_supersedes_plan(tmp_path: Path) -> None:
    path = _database(tmp_path, status="WAITING_APPROVAL", version=4)
    with connect_sqlite(path) as connection:
        connection.execute(
            """INSERT INTO plans (
                   id, run_id, revision_no, status, summary_text, created_at_ms,
                   review_status, review_version, review_disposition
               ) VALUES (
                   'plan-1', 'run-1', 1, 'WAITING_APPROVAL', 'Plan', 2,
                   'REQUIRED', 3, 'REVISE'
               );"""
        )
        connection.execute(
            """INSERT INTO actions (
                   id, plan_id, connector_id, position, tool_name, effect_type,
                   approval_requirement, verification_policy, recovery_policy,
                   target_resource_ref_id, status, arguments_json, arguments_hash,
                   expected_json, risk_json, version, created_at_ms, updated_at_ms
               ) VALUES (
                   'action-1', 'plan-1', 'google_workspace', 1, 'tasks_create_task',
                   'CREATE', 'REQUIRED', 'GET_COMPARE', 'RESOURCE_SEARCH', NULL,
                   'APPROVED', '{}', ?, '{}', '{}', 1, 2, 2
               );""",
            ("a" * 64,),
        )
        connection.execute(
            """INSERT INTO approvals (
                   id, action_id, approval_no, action_version, status,
                   approved_by_account_id, approved_by_display,
                   arguments_snapshot_json, canonical_arguments_hash,
                   source_snapshot_json, source_snapshot_hash, policy_version,
                   tool_schema_version, idempotency_key, recovery_fingerprint,
                   approved_at_ms, expires_at_ms, consumed_at_ms
               ) VALUES (
                   'approval-1', 'action-1', 1, 1, 'REVOKED', 'account-1', NULL,
                   '{}', ?, '{}', ?, 'v1', 'v1', ?, ?, 2, 1000, NULL
               );""",
            ("a" * 64, "b" * 64, "c" * 64, "d" * 64),
        )
        connection.commit()

    handler = BeginPlanningHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(path, now_ms=lambda: 10),
        checkpoint_port=SqliteCheckpointAdapter(path, now_ms=lambda: 10),
        now_ms=lambda: 10,
        id_factory=lambda: "unused-handoff",
        resume_target_registry=_ResumeTargetRegistry(),
    )
    result = handler(
        BeginPlanningCommand(
            run_id="run-1",
            expected_version=4,
            command_id="cmd-replan",
            request_hash="e" * 64,
            plan_id="plan-1",
            expected_review_version=3,
        )
    )
    assert result.applied

    with connect_sqlite(path) as connection:
        run = connection.execute("SELECT status, version FROM runs WHERE id='run-1';").fetchone()
        plan = connection.execute("SELECT status FROM plans WHERE id='plan-1';").fetchone()
        approval = connection.execute(
            "SELECT status FROM approvals WHERE id='approval-1';"
        ).fetchone()
    assert tuple(run) == ("PLANNING", 5)
    assert plan["status"] == "SUPERSEDED"
    assert approval["status"] == "REVOKED"


def test_audit_failure__rolls_back__run_and_receipt(tmp_path: Path) -> None:
    path = _database(tmp_path, status="CREATED")
    with connect_sqlite(path) as connection:
        connection.execute(
            """CREATE TRIGGER fail_run_phase_audit
               BEFORE INSERT ON audit_events
               BEGIN SELECT RAISE(ABORT, 'audit failure'); END;"""
        )
        connection.commit()

    handler = StartAnalysisHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(path, now_ms=lambda: 10),
        now_ms=lambda: 10,
    )
    with pytest.raises(Exception, match="audit failure"):
        handler(StartAnalysisCommand("run-1", 0, "cmd-start", "f" * 64))

    with connect_sqlite(path) as connection:
        run = connection.execute("SELECT status, version FROM runs WHERE id='run-1';").fetchone()
        receipt_count = connection.execute(
            "SELECT COUNT(*) AS count FROM command_receipts;"
        ).fetchone()
    assert tuple(run) == ("CREATED", 0)
    assert int(receipt_count["count"]) == 0


def test_published_reentry_with__inflight_action_has__zero_domain_mutation(tmp_path: Path) -> None:
    path = _database(tmp_path, status="VERIFYING", version=6)
    with connect_sqlite(path) as connection:
        connection.execute(
            """INSERT INTO plans (
                   id, run_id, revision_no, status, summary_text, created_at_ms,
                   review_status, review_version, review_disposition
               ) VALUES (
                   'plan-1', 'run-1', 1, 'WAITING_APPROVAL', 'Plan', 2,
                   'REQUIRED', 2, 'REVISE'
               );"""
        )
        connection.execute(
            """INSERT INTO actions (
                   id, plan_id, connector_id, position, tool_name, effect_type,
                   approval_requirement, verification_policy, recovery_policy,
                   target_resource_ref_id, status, arguments_json, arguments_hash,
                   expected_json, risk_json, version, created_at_ms, updated_at_ms
               ) VALUES (
                   'action-1', 'plan-1', 'google_workspace', 1, 'tasks_create_task',
                   'CREATE', 'REQUIRED', 'GET_COMPARE', 'RESOURCE_SEARCH', NULL,
                   'EXECUTING', '{}', ?, '{}', '{}', 1, 2, 2
               );""",
            ("a" * 64,),
        )
        connection.commit()

    handler = BeginPlanningHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(path, now_ms=lambda: 10),
        checkpoint_port=SqliteCheckpointAdapter(path, now_ms=lambda: 10),
        now_ms=lambda: 10,
        id_factory=lambda: "unused-handoff",
        resume_target_registry=_ResumeTargetRegistry(),
    )
    result = handler(
        BeginPlanningCommand(
            run_id="run-1",
            expected_version=6,
            command_id="cmd-inflight",
            request_hash="f" * 64,
            plan_id="plan-1",
            expected_review_version=2,
        )
    )
    assert not result.applied
    assert result.result_code == "STATE_CONFLICT"

    with connect_sqlite(path) as connection:
        run = connection.execute("SELECT status, version FROM runs WHERE id='run-1';").fetchone()
        plan = connection.execute("SELECT status FROM plans WHERE id='plan-1';").fetchone()
        audits = connection.execute(
            "SELECT COUNT(*) AS count FROM audit_events WHERE run_id='run-1';"
        ).fetchone()
    assert tuple(run) == ("VERIFYING", 6)
    assert plan["status"] == "WAITING_APPROVAL"
    assert int(audits["count"]) == 0


def test_context_adjustment_uses__retrieval_head_and__stages_resume_atomically(
    tmp_path: Path,
) -> None:
    path = _database(tmp_path, status="WAITING_APPROVAL", version=7)
    with connect_sqlite(path) as connection:
        connection.execute(
            """INSERT INTO plans (
                   id, run_id, revision_no, status, summary_text, created_at_ms,
                   review_status, review_version, review_disposition
               ) VALUES (
                   'plan-1', 'run-1', 1, 'WAITING_APPROVAL', 'Plan', 2,
                   'PASSED', 0, 'PASS'
               );"""
        )
        connection.execute(
            """INSERT INTO actions (
                   id, plan_id, connector_id, position, tool_name, effect_type,
                   approval_requirement, verification_policy, recovery_policy,
                   target_resource_ref_id, status, arguments_json, arguments_hash,
                   expected_json, risk_json, version, created_at_ms, updated_at_ms
               ) VALUES (
                   'action-1', 'plan-1', 'google_workspace', 1, 'tasks_create_task',
                   'CREATE', 'REQUIRED', 'GET_COMPARE', 'RESOURCE_SEARCH', NULL,
                   'PROPOSED', '{}', ?, '{}', '{}', 0, 2, 2
               );""",
            ("a" * 64,),
        )
        connection.commit()

    checkpoint = SqliteCheckpointAdapter(path, now_ms=lambda: 8)
    checkpoint.create_workflow_binding(
        WorkflowBindingV1(
            schema_version=1,
            workflow_key="workflow-1",
            run_id="run-1",
            langgraph_thread_id="thread-1",
            graph_profile="SIX_ROLE_BASELINE",
            graph_version="v1",
            requested_mode="AUTO",
            created_at_ms=1,
        )
    )
    checkpoint.flush()
    builder = StateGraph(_RetrievalState)
    builder.add_node("retrieval", lambda state: state)
    builder.add_edge(START, "retrieval")
    builder.add_edge("retrieval", END)
    graph = builder.compile(checkpointer=checkpoint)
    admission = WorkflowExecutionAdmissionV1(
        schema_version=1,
        admission_id="admission-1",
        handoff_id="initial-handoff",
        handoff_run_sequence=1,
        submission_kind="NORMAL_HANDOFF",
        effective_binding=WorkflowExecutionBindingV1(
            schema_version=1,
            execution_kind="START",
            run_id="run-1",
            langgraph_thread_id="thread-1",
            graph_profile="SIX_ROLE_BASELINE",
            graph_version="v1",
            requested_mode="AUTO",
            checkpoint_id=None,
            checkpoint_generation=0,
            resume_target=None,
        ),
        expected_run_version=7,
    )
    target = AgentNodeResumeTargetV2(
        kind="AGENT_NODE",
        semantic_owner_id="RETRIEVAL",
        compiled_subgraph_id="SIX_RETRIEVAL",
        node_id="retrieval.plan_query",
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="v1",
    )
    with checkpoint.execution_scope(
        admission,
        applied_handoff_id="initial-handoff",
        owner_scope="RETRIEVAL",
        resume_target=target,
    ):
        graph.invoke(
            {
                "retrieval_result": {
                    "schema_version": 1,
                    "meta": {"artifact_id": "retrieval-1", "revision": 2, "based_on": []},
                }
            },
            config={"configurable": {"thread_id": "thread-1"}},
        )
    checkpoint.close()

    handler = BeginPlanningHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(path, now_ms=lambda: 10),
        checkpoint_port=SqliteCheckpointAdapter(path, now_ms=lambda: 10),
        now_ms=lambda: 10,
        id_factory=lambda: "context-handoff-1",
        resume_target_registry=_ResumeTargetRegistry(),
    )
    result = handler(
        BeginPlanningCommand(
            run_id="run-1",
            expected_version=7,
            command_id="cmd-adjust",
            request_hash="f" * 64,
            plan_id="plan-1",
            expected_retrieval_revision=2,
            context_adjustment=ContextAdjustmentControlV1(
                kind="CONTEXT_ADJUSTMENT",
                adjustment={"kind": "RETRIEVE_MORE", "requested_information": "latest status"},
            ),
        )
    )
    assert result.applied
    assert result.handoff_id == "context-handoff-1"

    with connect_sqlite(path) as connection:
        handoff = connection.execute(
            """SELECT status, control_kind, checkpoint_id, checkpoint_generation
               FROM workflow_handoffs WHERE handoff_id='context-handoff-1';"""
        ).fetchone()
        run = connection.execute("SELECT status, version FROM runs WHERE id='run-1';").fetchone()
        plan = connection.execute("SELECT status FROM plans WHERE id='plan-1';").fetchone()
    assert tuple(run) == ("PLANNING", 8)
    assert plan["status"] == "SUPERSEDED"
    assert handoff["status"] == "PENDING"
    assert handoff["control_kind"] == "CONTEXT_ADJUSTMENT"
    assert handoff["checkpoint_id"] is not None
    assert handoff["checkpoint_generation"] >= 1
