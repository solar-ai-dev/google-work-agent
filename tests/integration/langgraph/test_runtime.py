from collections import deque
from pathlib import Path

from tests.integration.persistence.test_write_actions import _expected_task_projection
from tests.support.fakes import DeterministicUUID, FakeClock, FakeGoogleGateway
from tests.support.fixtures import ProductFixtureSnapshotLoader
from tests.unit.application.workflows.test_api_acquisition import _plan
from tests.unit.application.workflows.test_context_retrieval import _sufficiency_output
from tests.unit.application.workflows.test_plan_review import _review_output

from google_work_agent.adapters.langgraph import (
    GraphProfile,
    LangGraphWorkflowRuntime,
    PromptArtifactGapError,
    supported_graph_profiles,
)
from google_work_agent.adapters.persistence import (
    apply_migrations,
    connect_sqlite,
    sqlite_unit_of_work_factory,
)
from google_work_agent.application import ApproveWriteActionCommand, ApproveWriteActionService
from google_work_agent.ports import (
    ActualRuntime,
    RequestedRuntimeMode,
    StructuredLLMResult,
    WorkflowCorrelationContext,
    WorkflowOutcome,
    WorkflowResumeRequest,
    WorkflowStartRequest,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "product"


class _QueuedLLMRuntime:
    def __init__(self, payloads: list[object]) -> None:
        self._queued = deque(_llm_result(item) for item in payloads)

    def invoke_structured(self, **_: object) -> StructuredLLMResult:
        if not self._queued:
            raise RuntimeError("no queued llm result")
        return self._queued.popleft()


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


def _clear_intent() -> dict[str, object]:
    return {
        "schema_version": 1,
        "goal": {
            "summary": "Follow up on the user's Google Workspace request.",
            "user_visible_objective": "Resolve the user's Google Workspace request.",
        },
        "completion_criteria": ["Return a useful answer or plan."],
        "semantic_constraints": {
            "topics": [{"text": "follow up", "source_text": "follow up"}],
            "people": [{"mention": "Kim", "role_hint": None, "source_text": "Kim"}],
            "time": [],
            "sources": [{"source": "TASKS", "mention": "tasks", "confidence": "HIGH"}],
            "status_or_state": [],
            "negative_constraints": [],
            "policy_or_safety_constraints": [],
        },
        "ambiguity": {"is_ambiguous": False, "items": []},
        "unsupported_scope": {
            "is_unsupported": False,
            "reason_code": None,
            "explanation": None,
        },
    }


def _ambiguous_intent() -> dict[str, object]:
    payload = _clear_intent()
    payload["ambiguity"] = {
        "is_ambiguous": True,
        "items": [
            {
                "field_path": "semantic_constraints.people[0]",
                "reason_code": "INTENT_AMBIGUITY_MISSED",
                "user_question": "Which Kim do you mean?",
            }
        ],
    }
    return payload


def _analysis_output() -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "COMPLETE",
        "summary": "The task context is enough to decide the next step.",
        "findings": [
            {
                "schema_version": 1,
                "finding_id": "finding-1",
                "kind": "RELATIONSHIP",
                "statement": "The selected task provides enough context.",
                "evidence_refs": ["evidence-1"],
                "resource_refs": ["task:task-followup"],
                "segment_refs": ["seg-2"],
                "related_resource_handles": ["task:task-followup"],
                "reason_codes": ["EVIDENCE_SUPPORTED"],
            }
        ],
        "missing_information": [],
        "confirmation": None,
        "blockers": [],
        "evidence_refs": ["evidence-1"],
        "resource_refs": [
            {
                "resource_handle": "task:task-followup",
                "resource_type": "task",
                "resource_id": "task-followup",
            }
        ],
        "segment_refs": [
            {
                "segment_id": "seg-2",
                "resource_handle": "task:task-followup",
            }
        ],
    }


def _answer_output() -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "ANSWER_ONLY",
        "answer": "The follow-up task is identified and summarized for the user.",
        "evidence_refs": ["evidence-1"],
        "resource_refs": [
            {
                "resource_handle": "task:task-followup",
                "resource_type": "task",
                "resource_id": "task-followup",
            }
        ],
        "reason_codes": ["EVIDENCE_SUPPORTED"],
        "confirmation": None,
        "blockers": [],
    }


def _write_plan_output() -> dict[str, object]:
    payload = {
        "resource_id": "task-created-1",
        "title": "Send summary",
        "status": "needsAction",
    }
    expected = _expected_task_projection(
        resource_id="task-created-1",
        payload=payload,
        version="1",
    )
    return {
        "schema_version": 1,
        "status": "PLAN_READY",
        "plan_id": "plan-1",
        "summary": "Create the follow-up task requested by the user.",
        "objective": "Persist the follow-up task.",
        "actions": [
            {
                "schema_version": 1,
                "action_id": "action-1",
                "position": 1,
                "effect": "CREATE",
                "tool_name": "tasks_create_task",
                "arguments": {"task_list_id": "task-list-default", "payload": payload},
                "expected": expected,
                "evidence_refs": ["evidence-1"],
                "resource_refs": ["task:task-followup"],
                "target_resource_ref_id": None,
                "depends_on_action_ids": [],
                "user_visible_reason": "Create the requested follow-up task.",
            }
        ],
        "evidence_refs": ["evidence-1"],
        "resource_refs": [
            {
                "resource_handle": "task:task-followup",
                "resource_type": "task",
                "resource_id": "task-followup",
            }
        ],
        "confirmation": None,
    }


def _read_plan_output() -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "PLAN_READY",
        "plan_id": "plan-read-1",
        "summary": "Read the follow-up task details for the user.",
        "objective": "Retrieve the requested Google Tasks item.",
        "actions": [
            {
                "schema_version": 1,
                "action_id": "action-read-1",
                "position": 1,
                "effect": "READ",
                "tool_name": "tasks_get_task",
                "arguments": {"task_list_id": "task-list-default", "task_id": "task-followup"},
                "expected": {"resource_type": "task"},
                "evidence_refs": ["evidence-1"],
                "resource_refs": ["task:task-followup"],
                "target_resource_ref_id": None,
                "depends_on_action_ids": [],
                "user_visible_reason": "Read the requested follow-up task.",
            }
        ],
        "evidence_refs": ["evidence-1"],
        "resource_refs": [
            {
                "resource_handle": "task:task-followup",
                "resource_type": "task",
                "resource_id": "task-followup",
            }
        ],
        "confirmation": None,
    }


def _selection_output() -> dict[str, object]:
    return {
        "schema_version": 1,
        "result": "SELECTED",
        "selected_segment_ids": ["seg-2"],
        "evidence_drafts": [
            {
                "schema_version": 1,
                "evidence_id": "evidence-1",
                "resource_handle": "task:task-followup",
                "segment_id": "seg-2",
                "kind": "excerpt",
                "excerpt": "Reply to project sync",
                "locator": {"kind": "resource_payload"},
                "reason_codes": ["GOAL_RELEVANT"],
            }
        ],
        "excluded_resource_handles": [],
        "missing_information": [],
        "ambiguity": None,
    }


def _make_runtime(
    *,
    database_path: Path,
    llm_payloads: list[object],
    gateway: FakeGoogleGateway,
    checkpoint_database_path: Path,
    graph_profile: GraphProfile = GraphProfile.SIX_ROLE_BASELINE,
) -> LangGraphWorkflowRuntime:
    clock = FakeClock(1000)
    ids = DeterministicUUID(prefix="runtime")
    return LangGraphWorkflowRuntime(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        llm_runtime=_QueuedLLMRuntime(llm_payloads),
        gateway=gateway,
        now_ms=clock.now_ms,
        id_factory=ids.next_id,
        signing_secret="stage17-secret",
        service_instance_id="stage17-service",
        checkpoint_database_path=checkpoint_database_path,
        graph_profile=graph_profile,
    )


def _seed_runtime_database(tmp_path: Path, *, status: str = "CREATED") -> Path:
    database_path = tmp_path / "stage17-runtime.db"
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
                'run-1', 'conversation-1', 'AGENT_SEARCH', ?, 'thread-1',
                'AUTO', '{}', 0, 100
            );
            """,
            (status,),
        )
        connection.commit()
    finally:
        connection.close()
    return database_path


def _start_request() -> WorkflowStartRequest:
    return WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="Please handle the follow-up.",
        selected_resource_ids=(),
        correlation=WorkflowCorrelationContext(
            request_id="request-1",
            command_id="command-1",
            api_contract_version="1",
        ),
    )


def _start_write_request() -> WorkflowStartRequest:
    return WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="Create the follow-up task in Google Tasks.",
        selected_resource_ids=(),
        correlation=WorkflowCorrelationContext(
            request_id="request-1",
            command_id="command-1",
            api_contract_version="1",
        ),
    )


def _start_read_request() -> WorkflowStartRequest:
    return WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="Get the follow-up task details from Google Tasks.",
        selected_resource_ids=(),
        correlation=WorkflowCorrelationContext(
            request_id="request-1",
            command_id="command-1",
            api_contract_version="1",
        ),
    )


def test_langgraph_runtime_completes_answer_only_run(tmp_path: Path) -> None:
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _clear_intent(),
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output(),
            _review_output("PASS"),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-answer.db",
    )

    result = runtime.start(_start_request())

    assert result.outcome is WorkflowOutcome.COMPLETED
    connection = connect_sqlite(database_path)
    try:
        run_row = connection.execute(
            "SELECT status, version FROM runs WHERE id = 'run-1';"
        ).fetchone()
        message_count = connection.execute(
            "SELECT COUNT(*) FROM messages WHERE run_id = 'run-1' AND role = 'ASSISTANT';"
        ).fetchone()[0]
        plan_count = connection.execute(
            "SELECT COUNT(*) FROM plans WHERE run_id = 'run-1';"
        ).fetchone()[0]
        assert tuple(run_row) == ("COMPLETED", 4)
        assert message_count == 1
        assert plan_count == 0
    finally:
        connection.close()
        runtime.close()


def test_langgraph_runtime_interrupts_for_confirmation_and_resumes_same_thread(
    tmp_path: Path,
) -> None:
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[_ambiguous_intent()],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-confirm.db",
    )

    first = runtime.start(_start_request())

    assert first.outcome is WorkflowOutcome.ACCEPTED
    connection = connect_sqlite(database_path)
    try:
        run_row = connection.execute(
            "SELECT status, version FROM runs WHERE id = 'run-1';"
        ).fetchone()
        assert tuple(run_row) == ("WAITING_CONFIRMATION", 2)
    finally:
        connection.close()

    runtime.close()
    resumed_runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output(),
            _review_output("PASS"),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-confirm.db",
    )

    resumed = resumed_runtime.resume(
        WorkflowResumeRequest(
            run_id="run-1",
            workflow_key="thread-1",
            resume_kind="CONFIRMATION",
            resume_payload={
                "schema_version": 1,
                "response_kind": "FREE_TEXT",
                "selected_option_ids": [],
                "free_text": "I mean Kim from project alpha.",
            },
            correlation=WorkflowCorrelationContext(
                request_id="request-2",
                command_id="command-2",
                api_contract_version="1",
            ),
        )
    )

    assert resumed.outcome is WorkflowOutcome.COMPLETED
    connection = connect_sqlite(database_path)
    try:
        run_row = connection.execute("SELECT status FROM runs WHERE id = 'run-1';").fetchone()
        assert run_row[0] == "COMPLETED"
        snapshot = resumed_runtime._graph.get_state(  # noqa: SLF001
            resumed_runtime._config_for_thread("thread-1")  # noqa: SLF001
        )
        request = snapshot.values["__request__"]
        assert request.request_text == "Please handle the follow-up."
        assert snapshot.values["prompt_context"]["confirmation_response"]["free_text"] == (
            "I mean Kim from project alpha."
        )
    finally:
        connection.close()
        resumed_runtime.close()


def test_langgraph_runtime_executes_verified_write_after_approval_resume(tmp_path: Path) -> None:
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _clear_intent(),
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _write_plan_output(),
            _review_output("PASS"),
        ],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-write.db",
    )

    started = runtime.start(_start_write_request())

    assert started.outcome is WorkflowOutcome.ACCEPTED
    approve_service = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 1000,
    )
    approve_response = approve_service(
        ApproveWriteActionCommand(
            command_id="approve-1",
            request_hash="a" * 64,
            action_id="action-1",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-1",
            idempotency_key="b" * 64,
        )
    )
    assert approve_response.applied is True

    resumed = runtime.resume(
        WorkflowResumeRequest(
            run_id="run-1",
            workflow_key="thread-1",
            resume_kind="APPROVAL",
            resume_payload={"approved": True},
            correlation=WorkflowCorrelationContext(
                request_id="request-2",
                command_id="command-2",
                api_contract_version="1",
            ),
        )
    )

    assert resumed.outcome is WorkflowOutcome.COMPLETED
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            """
            SELECT
                (SELECT status FROM runs WHERE id = 'run-1') AS run_status,
                (SELECT status FROM actions WHERE id = 'action-1') AS action_status;
            """
        ).fetchone()
        verification_count = connection.execute("SELECT COUNT(*) FROM verifications;").fetchone()[0]
        assert tuple(row) == ("COMPLETED", "VERIFIED")
        assert verification_count == 1
        assert any(call.operation == "create_task" for call in gateway.call_log)
        assert any(call.operation == "get_task" for call in gateway.call_log)
    finally:
        connection.close()
        runtime.close()


def test_langgraph_runtime_executes_read_only_plan_to_terminal(tmp_path: Path) -> None:
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _clear_intent(),
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _read_plan_output(),
            _review_output("PASS"),
        ],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-read.db",
    )

    result = runtime.start(_start_read_request())

    assert result.outcome is WorkflowOutcome.COMPLETED
    connection = connect_sqlite(database_path)
    try:
        counts = connection.execute(
            """
            SELECT
                (SELECT status FROM runs WHERE id = 'run-1') AS run_status,
                (SELECT status FROM actions WHERE id = 'action-read-1') AS action_status,
                (SELECT COUNT(*) FROM approvals) AS approval_count,
                (SELECT COUNT(*) FROM execution_attempts) AS attempt_count,
                (SELECT COUNT(*) FROM verifications) AS verification_count;
            """
        ).fetchone()
        assert tuple(counts) == ("COMPLETED", "VERIFIED", 0, 0, 0)
        assert any(call.operation == "get_task" for call in gateway.call_log)
    finally:
        connection.close()
        runtime.close()


def test_langgraph_runtime_supports_same_database_for_domain_and_checkpointer(
    tmp_path: Path,
) -> None:
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _clear_intent(),
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output(),
            _review_output("PASS"),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=database_path,
    )

    result = runtime.start(_start_request())

    assert result.outcome is WorkflowOutcome.COMPLETED
    connection = connect_sqlite(database_path)
    try:
        checkpoint_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'checkpoints%';"
            ).fetchall()
        }
        assert checkpoint_tables
    finally:
        connection.close()
        runtime.close()


def test_graph_profile_registry_exposes_three_supported_profiles() -> None:
    assert supported_graph_profiles() == (
        GraphProfile.SINGLE_BASELINE,
        GraphProfile.THREE_STAGE,
        GraphProfile.SIX_ROLE_BASELINE,
    )


def test_langgraph_runtime_reports_distinct_topologies_by_profile(tmp_path: Path) -> None:
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    six = _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-six.db",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
    )
    three = _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-three.db",
        graph_profile=GraphProfile.THREE_STAGE,
    )

    try:
        assert six.describe_topology() == (
            "request_understanding",
            "source_planning",
            "api_acquisition",
            "context_retrieval",
            "work_analysis",
            "solution_planning",
            "plan_review",
            "domain_validation",
        )
        assert three.describe_topology() == ("stage_one", "stage_two", "stage_three")
        assert six.describe_topology() != three.describe_topology()
    finally:
        six.close()
        three.close()


def test_single_baseline_reports_prompt_artifact_gap(tmp_path: Path) -> None:
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")

    try:
        _make_runtime(
            database_path=database_path,
            llm_payloads=[],
            gateway=FakeGoogleGateway(snapshot),
            checkpoint_database_path=tmp_path / "checkpoints-single.db",
            graph_profile=GraphProfile.SINGLE_BASELINE,
        )
    except PromptArtifactGapError as error:
        assert "PROMPT_ARTIFACT_GAP" in str(error)
    else:
        raise AssertionError("SINGLE_BASELINE should fail without a unified prompt artifact")


def test_three_stage_runtime_completes_answer_only_run(tmp_path: Path) -> None:
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _clear_intent(),
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output(),
            _review_output("PASS"),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-three-answer.db",
        graph_profile=GraphProfile.THREE_STAGE,
    )

    result = runtime.start(_start_request())

    assert result.outcome is WorkflowOutcome.COMPLETED
    assert result.payload["graph_profile"] == GraphProfile.THREE_STAGE.value
    connection = connect_sqlite(database_path)
    try:
        run_row = connection.execute(
            "SELECT status, version FROM runs WHERE id = 'run-1';"
        ).fetchone()
        assert tuple(run_row) == ("COMPLETED", 4)
    finally:
        connection.close()
        runtime.close()


def test_resume_rejects_profile_change_for_same_thread(tmp_path: Path) -> None:
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    three_runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[_ambiguous_intent()],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-profile.db",
        graph_profile=GraphProfile.THREE_STAGE,
    )
    first = three_runtime.start(_start_request())
    assert first.outcome is WorkflowOutcome.ACCEPTED
    three_runtime.close()

    six_runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-profile.db",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
    )

    resumed = six_runtime.resume(
        WorkflowResumeRequest(
            run_id="run-1",
            workflow_key="thread-1",
            resume_kind="CONFIRMATION",
            resume_payload={
                "schema_version": 1,
                "response_kind": "FREE_TEXT",
                "selected_option_ids": [],
                "free_text": "I mean Kim from project alpha.",
            },
            correlation=WorkflowCorrelationContext(
                request_id="request-2",
                command_id="command-2",
                api_contract_version="1",
            ),
        )
    )

    try:
        assert resumed.outcome is WorkflowOutcome.DOMAIN_CHECKPOINT_CONFLICT
        assert resumed.payload["graph_profile"] == GraphProfile.SIX_ROLE_BASELINE.value
    finally:
        six_runtime.close()
