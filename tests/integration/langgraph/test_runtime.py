from collections import deque
from pathlib import Path

import pytest
from tests.integration.persistence.test_write_actions import _expected_task_projection
from tests.support.fakes import (
    DeterministicUUID,
    FakeClock,
    FakeGoogleGateway,
    GoogleGatewayFault,
    GoogleGatewayFaultKind,
)
from tests.support.fixtures import ProductFixtureSnapshotLoader
from tests.support.prompt_manifests import write_runtime_active_manifest
from tests.unit.application.workflows.test_api_acquisition import _plan
from tests.unit.application.workflows.test_context_retrieval import _sufficiency_output
from tests.unit.application.workflows.test_plan_review import _review_output

from google_work_agent.adapters.langgraph import (
    GraphProfile,
    LangGraphWorkflowRuntime,
    supported_graph_profiles,
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
    StoreWriteActionSuccessCommand,
)
from google_work_agent.application.workflows.prompt_registry import InactivePromptArtifactError
from google_work_agent.ports import (
    ActualRuntime,
    RequestedRuntimeMode,
    StructuredLLMResult,
    WorkflowCorrelationContext,
    WorkflowOutcome,
    WorkflowRecoveryRequest,
    WorkflowResumeRequest,
    WorkflowStartRequest,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "product"
_RUNTIME_ACTIVE_PROMPT_IDS = {
    "request_understanding.classify",
    "request_understanding.clarify",
    "acquisition.plan_sources",
    "context.select_evidence",
    "context.assess_sufficiency",
    "analysis.analyze",
    "planning.answer_only",
    "planning.draft_plan",
    "planning.revise_plan",
    "review.inspect",
    "review.recheck",
    "profile.single.request_source.initial",
    "profile.single.reason_plan.initial",
    "profile.single.self_review.initial",
    "profile.single.self_review.recheck",
    "profile.three.stage1.initial",
    "profile.three.stage2.initial",
}


class _QueuedLLMRuntime:
    def __init__(self, payloads: list[object]) -> None:
        self._queued = deque(_llm_result(item) for item in payloads)
        self.calls: list[dict[str, object]] = []

    def invoke_structured(self, **kwargs: object) -> StructuredLLMResult:
        self.calls.append(dict(kwargs))
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
        "schema_version": 2,
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
        "schema_version": 2,
        "status": "PLAN_READY",
        "plan_id": "plan-1",
        "summary": "Create the follow-up task requested by the user.",
        "objective": "Persist the follow-up task.",
        "actions": [
            {
                "schema_version": 2,
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


def _send_write_plan_output() -> dict[str, object]:
    plan = _write_plan_output()
    action = plan["actions"][0]
    action.update(
        {
            "effect": "SEND",
            "tool_name": "gmail_send",
            "arguments": {"draft_id": "draft-followup"},
            "expected": {
                "resource_type": "gmail_message",
                "resource_id": "sent-draft-followup",
                "parent_id": "thread-project",
                "version": "1",
                "payload": {
                    "thread_id": "thread-project",
                    "to": ["pm@example.com"],
                    "subject": "Re: Project sync follow-up",
                    "body": "Draft summary is ready for review.",
                    "draft_id": "draft-followup",
                    "sent": True,
                    "resource_id": "sent-draft-followup",
                },
            },
            "user_visible_reason": "Send the approved Gmail draft.",
        }
    )
    plan["summary"] = "Send the approved Gmail draft requested by the user."
    return plan


def _delete_write_plan_output() -> dict[str, object]:
    plan = _write_plan_output()
    action = plan["actions"][0]
    action.update(
        {
            "effect": "DELETE",
            "tool_name": "calendar_delete_event",
            "arguments": {"calendar_id": "calendar-primary", "event_id": "event-focus"},
            "expected": {
                "resource_type": "calendar_event",
                "resource_id": "event-focus",
                "absent": True,
            },
            "resource_refs": ["calendar_event:event-focus"],
            "target_resource_ref_id": "calendar_event:event-focus",
            "user_visible_reason": "Delete the approved single calendar event.",
        }
    )
    plan["summary"] = "Delete the approved single calendar event requested by the user."
    plan["resource_refs"] = [
        {
            "resource_handle": "calendar_event:event-focus",
            "resource_type": "calendar_event",
            "resource_id": "event-focus",
        }
    ]
    return plan


def _read_plan_output() -> dict[str, object]:
    return {
        "schema_version": 2,
        "status": "PLAN_READY",
        "plan_id": "plan-read-1",
        "summary": "Read the follow-up task details for the user.",
        "objective": "Retrieve the requested Google Tasks item.",
        "actions": [
            {
                "schema_version": 2,
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


def _context_result(status: str = "SUFFICIENT") -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": status,
        "context_bundle": {
            "schema_version": 1,
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
            "evidence_refs": ["evidence-1"],
            "normalized_context": [],
            "missing_information": [],
            "ambiguity": None,
        },
        "evidence_drafts": list(_selection_output()["evidence_drafts"]),
        "selected_segment_ids": ["seg-2"],
        "excluded_resource_handles": [],
        "missing_slots": [],
        "additional_acquisition_request": None,
        "sufficiency": {"summary": "enough"},
        "llm_provider_result": {
            "provider": "fake",
            "model": "fake-model",
            "requested_mode": "AUTO",
            "actual_runtime": "API_LLM",
            "input_tokens": 10,
            "output_tokens": 20,
            "total_tokens": 30,
            "latency_ms": 5,
            "fallback_reason": None,
            "structured_output_attempts": 1,
            "provider_request_id": "provider-request-1",
            "safe_error_code": None,
        },
    }


def _source_plan_output(result: str = "PLAN_READY") -> dict[str, object]:
    fetch_plans = (
        [_plan("TASKS", {"task_list_id": "task-list-default"})] if result == "PLAN_READY" else []
    )
    clarification = None
    failure = None
    if result == "NEEDS_CONFIRMATION":
        clarification = {
            "schema_version": 1,
            "question": "Which task list should I inspect?",
            "reason_code": "QUERY_SCOPE_EXPANSION_REQUIRES_CONFIRMATION",
            "affected_field_paths": ["semantic_constraints.sources[0]"],
            "options": [],
        }
    if result == "BLOCKED":
        failure = {
            "schema_version": 1,
            "reason_code": "SOURCE_PLANNING_BLOCKED",
            "user_safe_message": "Source planning is blocked.",
            "diagnostic": "blocked in test fixture",
        }
    return {
        "schema_version": 1,
        "result": result,
        "source_fetch_plans": fetch_plans,
        "clarification": clarification,
        "failure": failure,
        "validator_codes": [result],
    }


def _calendar_intent() -> dict[str, object]:
    intent = _clear_intent()
    intent["semantic_constraints"]["sources"] = [
        {"source": "CALENDAR", "mention": "calendar", "confidence": "HIGH"}
    ]
    return intent


def _calendar_selection_output() -> dict[str, object]:
    return {
        "schema_version": 1,
        "result": "SELECTED",
        "selected_segment_ids": ["seg-1"],
        "evidence_drafts": [
            {
                "schema_version": 1,
                "evidence_id": "evidence-1",
                "resource_handle": "calendar_event:event-focus",
                "segment_id": "seg-1",
                "kind": "excerpt",
                "excerpt": "Focus block",
                "locator": {"kind": "resource_payload"},
                "reason_codes": ["GOAL_RELEVANT"],
            }
        ],
        "excluded_resource_handles": [],
        "missing_information": [],
        "ambiguity": None,
    }


def _calendar_analysis_output() -> dict[str, object]:
    result = _analysis_output()
    finding = result["findings"][0]
    finding["resource_refs"] = ["calendar_event:event-focus"]
    finding["related_resource_handles"] = ["calendar_event:event-focus"]
    finding["segment_refs"] = ["seg-1"]
    result["resource_refs"] = [
        {
            "resource_handle": "calendar_event:event-focus",
            "resource_type": "calendar_event",
            "resource_id": "event-focus",
        }
    ]
    result["segment_refs"] = [
        {"segment_id": "seg-1", "resource_handle": "calendar_event:event-focus"}
    ]
    return result


def _profile_request_source_output(result: str = "PLAN_READY") -> dict[str, object]:
    return {
        "schema_version": 2,
        "request_intent": _clear_intent(),
        "source_plan": _source_plan_output(result),
    }


def _profile_planning_projection(
    status: str = "ANSWER_ONLY",
) -> dict[str, object]:
    answer_draft = _answer_output() if status == "ANSWER_ONLY" else None
    plan_draft = _write_plan_output() if status == "PLAN_READY" else None
    return {
        "schema_version": 2,
        "status": status,
        "answer_draft": answer_draft,
        "plan_draft": plan_draft,
    }


def _profile_reason_plan_output(
    status: str = "ANSWER_ONLY",
) -> dict[str, object]:
    return {
        "schema_version": 2,
        "context_result": _context_result(),
        "analysis_result": _analysis_output(),
        "planning_result": _profile_planning_projection(status),
    }


def _make_runtime(
    *,
    database_path: Path,
    llm_payloads: list[object],
    gateway: FakeGoogleGateway,
    checkpoint_database_path: Path,
    graph_profile: GraphProfile = GraphProfile.SIX_ROLE_BASELINE,
    prompt_manifest_path: Path | None = None,
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
        prompt_manifest_path=prompt_manifest_path,
    )


def _runtime_active_manifest_path(tmp_path: Path) -> Path:
    return write_runtime_active_manifest(
        tmp_path,
        prompt_ids=_RUNTIME_ACTIVE_PROMPT_IDS,
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


def test_langgraph_runtime_completes_answer_only_run(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
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
        prompt_manifest_path=manifest_path,
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
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[_ambiguous_intent()],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-confirm.db",
        prompt_manifest_path=manifest_path,
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
        prompt_manifest_path=manifest_path,
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


def test_langgraph_runtime_executes_verified_write_after_approval_resume(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
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
        prompt_manifest_path=manifest_path,
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


def test_langgraph_runtime_restart_verifies_executed_action_without_replaying_write(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    checkpoint_path = tmp_path / "checkpoints-executed-restart.db"
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
        checkpoint_database_path=checkpoint_path,
        prompt_manifest_path=manifest_path,
    )
    assert runtime.start(_start_write_request()).outcome is WorkflowOutcome.ACCEPTED
    approved = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 1000,
    )(
        ApproveWriteActionCommand(
            command_id="approve-before-restart",
            request_hash="e" * 64,
            action_id="action-1",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id="approval-before-restart",
            idempotency_key="f" * 64,
        )
    )
    assert approved.applied is True

    with sqlite_unit_of_work_factory(database_path)() as unit_of_work:
        unit_of_work.runs.set_verifying("run-1")
        unit_of_work.commit()
    runtime._preflight_write(action_id="action-1")  # noqa: SLF001
    claim = runtime._claim_write(  # noqa: SLF001
        ClaimWriteActionCommand(
            command_id="claim-before-restart",
            request_hash="1" * 64,
            action_id="action-1",
            expected_version=approved.action_version,
            source_snapshot={},
            attempt_id="attempt-before-restart",
            nonce="nonce-before-restart",
        )
    )
    executed = runtime._execute_write(  # noqa: SLF001
        action_id="action-1",
        claim_token=claim.claim_token,
    )
    runtime._store_write_success(  # noqa: SLF001
        StoreWriteActionSuccessCommand(
            command_id="store-before-restart",
            request_hash="2" * 64,
            action_id="action-1",
            attempt_id="attempt-before-restart",
            expected_action_version=claim.action_version,
            expected_attempt_version=0,
            snapshot=executed.snapshot,
        )
    )
    assert gateway.count_calls("create_task") == 1
    runtime.close()

    restarted = _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=gateway,
        checkpoint_database_path=checkpoint_path,
        prompt_manifest_path=manifest_path,
    )
    recovered = restarted.recover_open_run(
        WorkflowRecoveryRequest(
            run_id="run-1",
            workflow_key="thread-1",
            domain_status="VERIFYING",
            domain_version=3,
            correlation=WorkflowCorrelationContext(
                request_id="startup-recovery",
                command_id=None,
                api_contract_version="1",
            ),
        )
    )

    assert recovered.outcome is WorkflowOutcome.COMPLETED
    assert gateway.count_calls("create_task") == 1
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            """
            SELECT
                (SELECT status FROM runs WHERE id = 'run-1'),
                (SELECT status FROM actions WHERE id = 'action-1'),
                (SELECT COUNT(*) FROM execution_attempts),
                (SELECT COUNT(*) FROM verifications);
            """
        ).fetchone()
        assert tuple(row) == ("COMPLETED", "VERIFIED", 1, 1)
    finally:
        connection.close()
        restarted.close()


@pytest.mark.parametrize(
    ("plan_output", "expected_operation", "calendar_context", "recovery_fault"),
    [
        (_send_write_plan_output, "send_gmail", False, None),
        (_delete_write_plan_output, "delete_calendar_event", True, None),
        (_send_write_plan_output, "send_gmail", False, GoogleGatewayFaultKind.HTTP_500),
    ],
)
def test_langgraph_runtime_executes_send_and_delete_after_approval_resume(
    tmp_path: Path,
    plan_output: object,
    expected_operation: str,
    calendar_context: bool,
    recovery_fault: GoogleGatewayFaultKind | None,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    llm_payloads = (
        [
            _calendar_intent(),
            [_plan("CALENDAR", {"calendar_id": "calendar-primary"})],
            _calendar_selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _calendar_analysis_output(),
            plan_output(),
            _review_output("PASS"),
        ]
        if calendar_context
        else [
            _clear_intent(),
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            plan_output(),
            _review_output("PASS"),
        ]
    )
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=llm_payloads,
        gateway=gateway,
        checkpoint_database_path=tmp_path / f"checkpoints-{expected_operation}.db",
        prompt_manifest_path=manifest_path,
    )

    started = runtime.start(_start_write_request())
    assert started.outcome is WorkflowOutcome.ACCEPTED
    approved = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 1000,
    )(
        ApproveWriteActionCommand(
            command_id=f"approve-{expected_operation}",
            request_hash="c" * 64,
            action_id="action-1",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id=f"approval-{expected_operation}",
            idempotency_key="d" * 64,
        )
    )
    assert approved.applied is True
    if recovery_fault is not None:
        gateway.queue_fault(
            operation=expected_operation,
            fault=GoogleGatewayFault(recovery_fault),
        )

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
        row = connection.execute("SELECT status FROM actions WHERE id = 'action-1';").fetchone()
        assert row[0] == "VERIFIED"
        assert any(call.operation == expected_operation for call in gateway.call_log)
        if recovery_fault is not None:
            assert gateway.count_calls("send_gmail") == 1
            assert gateway.count_calls("search_by_recovery_fingerprint") == 1
    finally:
        connection.close()
        runtime.close()


def test_langgraph_runtime_executes_read_only_plan_to_terminal(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
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
        prompt_manifest_path=manifest_path,
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
    manifest_path = _runtime_active_manifest_path(tmp_path)
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
        prompt_manifest_path=manifest_path,
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


def test_langgraph_runtime_reports_distinct_topologies_by_profile(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    six = _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-six.db",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )
    three = _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-three.db",
        graph_profile=GraphProfile.THREE_STAGE,
        prompt_manifest_path=manifest_path,
    )
    single = _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-single.db",
        graph_profile=GraphProfile.SINGLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )

    try:
        assert six.describe_topology() == (
            "request_understanding",
            "acquisition",
            "context_retriever",
            "work_analysis",
            "planning",
            "review",
        )
        assert three.describe_topology() == ("stage_one", "stage_two", "stage_three")
        assert single.describe_topology() == ("single_workflow",)
        assert six.describe_topology() != three.describe_topology()
        assert single.describe_topology() != three.describe_topology()
    finally:
        six.close()
        three.close()
        single.close()


def test_six_role_runtime_exposes_six_native_agent_subgraphs(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-subgraphs.db",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )

    try:
        assert tuple(runtime._native_agent_subgraphs) == (  # noqa: SLF001
            "request_understanding",
            "acquisition",
            "context_retriever",
            "work_analysis",
            "planning",
            "review",
        )
        assert len(runtime._native_agent_subgraphs) == 6  # noqa: SLF001
        assert runtime._node_handler("request_understanding") is runtime._request_subgraph  # noqa: SLF001
        assert runtime._node_handler("acquisition") is runtime._acquisition_subgraph  # noqa: SLF001
        assert runtime._node_handler("context_retriever") is runtime._context_subgraph  # noqa: SLF001
        assert runtime._node_handler("work_analysis") is runtime._analysis_subgraph  # noqa: SLF001
        assert runtime._node_handler("planning") is runtime._planning_subgraph  # noqa: SLF001
        assert runtime._node_handler("review") is runtime._review_subgraph  # noqa: SLF001
    finally:
        runtime.close()


def test_native_profile_runtimes_expose_three_and_single_subgraphs(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    three = _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-three-subgraphs.db",
        graph_profile=GraphProfile.THREE_STAGE,
        prompt_manifest_path=manifest_path,
    )
    single = _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-single-subgraphs.db",
        graph_profile=GraphProfile.SINGLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )

    try:
        assert tuple(three._native_agent_subgraphs) == ("stage_one", "stage_two", "stage_three")  # noqa: SLF001
        assert three._node_handler("stage_one") is three._three_stage_one_subgraph  # noqa: SLF001
        assert three._node_handler("stage_two") is three._three_stage_two_subgraph  # noqa: SLF001
        assert three._node_handler("stage_three") is three._three_stage_review_subgraph  # noqa: SLF001
        assert tuple(single._native_agent_subgraphs) == ("single_workflow",)  # noqa: SLF001
        assert single._node_handler("single_workflow") is single._single_workflow_subgraph  # noqa: SLF001
    finally:
        three.close()
        single.close()


def test_request_subgraph_clears_local_state_and_records_trace_counts(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[_clear_intent()],
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints-request-subgraph.db",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )

    try:
        state = runtime._initial_state(_start_request())  # noqa: SLF001
        result = runtime._request_subgraph.invoke(state)  # noqa: SLF001

        assert "__request_agent_local__" not in result
        assert result["__logical_target__"] == "acquisition"
        assert result["__target__"] == "acquisition"
        trace_context = result["trace_context"]
        assert trace_context["agent_invocation_count"] == 1
        assert trace_context["llm_call_count"] == 1
        assert [item["node_name"] for item in trace_context["agent_node_log"]] == [
            "init",
            "classify",
            "finalize",
        ]
    finally:
        runtime.close()


def test_acquisition_subgraph_keeps_single_invocation_id_and_parent_isolation(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    llm_runtime = _QueuedLLMRuntime([[_plan("TASKS", {"task_list_id": "task-list-default"})]])
    runtime = LangGraphWorkflowRuntime(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        llm_runtime=llm_runtime,
        gateway=gateway,
        now_ms=FakeClock(1000).now_ms,
        id_factory=DeterministicUUID(prefix="runtime").next_id,
        signing_secret="stage17-secret",
        service_instance_id="stage17-service",
        checkpoint_database_path=tmp_path / "checkpoints-acquisition-subgraph.db",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )

    try:
        state = runtime._initial_state(_start_request())  # noqa: SLF001
        state["request_intent"] = _clear_intent()
        result = runtime._acquisition_subgraph.invoke(state)  # noqa: SLF001

        assert "__request_agent_local__" not in result
        assert "__acquisition_agent_local__" not in result
        assert "__acquisition_planning_output__" not in result
        assert result["__logical_target__"] == "context_retriever"
        assert result["__target__"] == "context_retriever"
        assert gateway.count_calls("list_tasks") == 1
        assert gateway.count_calls("get_task") >= 1
        assert gateway.count_calls("search_gmail_threads") == 0
        assert gateway.count_calls("list_calendar_events") == 0
        assert len(llm_runtime.calls) == 1

        trace_context = result["trace_context"]
        assert trace_context["agent_invocation_count"] == 1
        assert trace_context["llm_call_count"] == 1
        node_log = trace_context["agent_node_log"]
        assert [item["node_name"] for item in node_log] == [
            "init",
            "plan_sources",
            "plan_validate",
            "deterministic_read",
            "result_validate",
            "finalize",
        ]
        invocation_ids = {item["agent_invocation_id"] for item in node_log}
        assert len(invocation_ids) == 1
        assert {item["agent_subgraph_id"] for item in node_log} == {"acquisition"}
    finally:
        runtime.close()


def test_six_role_full_path_records_six_agent_invocations_and_seven_llm_calls(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
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
        checkpoint_database_path=tmp_path / "checkpoints-six-full.db",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )

    try:
        result = runtime.start(_start_request())
        snapshot_state = runtime._graph.get_state(runtime._config_for_thread("thread-1"))  # noqa: SLF001
        values = snapshot_state.values

        assert result.outcome is WorkflowOutcome.COMPLETED
        trace_context = values["trace_context"]
        assert trace_context["agent_invocation_count"] == 6
        assert trace_context["llm_call_count"] == 7
        init_log = [
            item["agent_subgraph_id"]
            for item in trace_context["agent_node_log"]
            if item["node_name"] == "init"
        ]
        assert init_log == [
            "request_understanding",
            "acquisition",
            "context_retriever",
            "work_analysis",
            "planning",
            "review",
        ]
        invocation_ids = {item["agent_invocation_id"] for item in trace_context["agent_node_log"]}
        assert len(invocation_ids) == 6
    finally:
        runtime.close()


def test_context_subgraph_routes_needs_more_data_back_to_parent_acquisition(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("NEEDS_MORE_DATA"),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-context-route.db",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )

    try:
        state = runtime._initial_state(_start_request())  # noqa: SLF001
        state["request_intent"] = _clear_intent()
        acquired = runtime._acquisition_subgraph.invoke(state)  # noqa: SLF001
        routed = runtime._context_subgraph.invoke(acquired)  # noqa: SLF001

        assert routed["__logical_target__"] == "acquisition"
        assert routed["__target__"] == "acquisition"
        assert "__context_agent_local__" not in routed
    finally:
        runtime.close()


def test_agent_subgraphs_route_by_logical_target_without_direct_peer_invocation(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _clear_intent(),
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("NEEDS_MORE_DATA"),
            _review_output(
                "REVISE",
                issues=[
                    {
                        "schema_version": 2,
                        "issue_id": "issue-1",
                        "kind": "MISSING_GOAL_COVERAGE",
                        "message": "Need a revision.",
                        "affected_action_ids": [],
                        "affected_field_paths": ["$.answer"],
                        "evidence_refs": ["evidence-1"],
                        "resource_refs": ["task:task-followup"],
                        "reason_codes": ["EVIDENCE_SUPPORTED"],
                    }
                ],
            ),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-no-direct-peer.db",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )

    peer_invocations: list[str] = []

    def _forbid_peer_invoke(peer_name: str):
        def _raise(*args: object, **kwargs: object) -> object:
            peer_invocations.append(peer_name)
            raise AssertionError(f"unexpected direct peer invoke: {peer_name}")

        return _raise

    original_acquisition_invoke = runtime._acquisition_subgraph.invoke  # noqa: SLF001
    original_context_invoke = runtime._context_subgraph.invoke  # noqa: SLF001
    original_planning_invoke = runtime._planning_subgraph.invoke  # noqa: SLF001

    try:
        runtime._acquisition_subgraph.invoke = _forbid_peer_invoke("acquisition")  # type: ignore[method-assign]  # noqa: SLF001
        request_state = runtime._initial_state(_start_request())  # noqa: SLF001
        request_result = runtime._request_subgraph.invoke(request_state)  # noqa: SLF001
        assert request_result["__target__"] == "acquisition"

        runtime._acquisition_subgraph.invoke = original_acquisition_invoke  # type: ignore[method-assign]  # noqa: SLF001
        runtime._context_subgraph.invoke = _forbid_peer_invoke("context_retriever")  # type: ignore[method-assign]  # noqa: SLF001
        acquisition_state = runtime._initial_state(_start_request())  # noqa: SLF001
        acquisition_state["request_intent"] = _clear_intent()
        acquisition_result = runtime._acquisition_subgraph.invoke(acquisition_state)  # noqa: SLF001
        assert acquisition_result["__target__"] == "context_retriever"

        runtime._context_subgraph.invoke = original_context_invoke  # type: ignore[method-assign]  # noqa: SLF001
        runtime._acquisition_subgraph.invoke = _forbid_peer_invoke("acquisition")  # type: ignore[method-assign]  # noqa: SLF001
        routed = runtime._context_subgraph.invoke(acquisition_result)  # noqa: SLF001
        assert routed["__target__"] == "acquisition"

        runtime._acquisition_subgraph.invoke = original_acquisition_invoke  # type: ignore[method-assign]  # noqa: SLF001
        runtime._planning_subgraph.invoke = _forbid_peer_invoke("planning")  # type: ignore[method-assign]  # noqa: SLF001
        review_state = runtime._initial_state(_start_request())  # noqa: SLF001
        review_state["request_intent"] = _clear_intent()
        review_state["context_result"] = _context_result()
        review_state["analysis_result"] = _analysis_output()
        review_state["answer_draft"] = _answer_output()
        review_result = runtime._review_subgraph.invoke(review_state)  # noqa: SLF001
        assert review_result["__target__"] == "planning"

        assert peer_invocations == []
    finally:
        runtime._acquisition_subgraph.invoke = original_acquisition_invoke  # type: ignore[method-assign]  # noqa: SLF001
        runtime._context_subgraph.invoke = original_context_invoke  # type: ignore[method-assign]  # noqa: SLF001
        runtime._planning_subgraph.invoke = original_planning_invoke  # type: ignore[method-assign]  # noqa: SLF001
        runtime.close()


def test_review_subgraph_routes_revise_and_retrieve_more_through_parent(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    issue = {
        "schema_version": 2,
        "issue_id": "issue-1",
        "kind": "MISSING_GOAL_COVERAGE",
        "message": "Need a revision.",
        "affected_action_ids": [],
        "affected_field_paths": ["$.answer"],
        "evidence_refs": ["evidence-1"],
        "resource_refs": ["task:task-followup"],
        "reason_codes": ["EVIDENCE_SUPPORTED"],
    }
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _review_output("REVISE", issues=[issue]),
            _review_output("RETRIEVE_MORE", issues=[issue]),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-review-route.db",
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )

    try:
        base_state = runtime._initial_state(_start_request())  # noqa: SLF001
        base_state["request_intent"] = _clear_intent()
        base_state["context_result"] = _context_result()
        base_state["analysis_result"] = _analysis_output()
        base_state["answer_draft"] = _answer_output()

        revise_state = runtime._review_subgraph.invoke(dict(base_state))  # noqa: SLF001
        assert revise_state["__logical_target__"] == "planning"
        assert revise_state["__target__"] == "planning"

        retrieve_state = runtime._review_subgraph.invoke(dict(base_state))  # noqa: SLF001
        assert retrieve_state["__logical_target__"] == "acquisition"
        assert retrieve_state["__target__"] == "acquisition"
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "graph_profile",
    [
        GraphProfile.SIX_ROLE_BASELINE,
        GraphProfile.SINGLE_BASELINE,
        GraphProfile.THREE_STAGE,
    ],
)
def test_agent_subgraphs_do_not_issue_google_writes_before_approval(
    tmp_path: Path,
    graph_profile: GraphProfile,
) -> None:
    root = tmp_path / graph_profile.value.lower()
    root.mkdir()
    manifest_path = _runtime_active_manifest_path(root)
    database_path = _seed_runtime_database(root)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    llm_payloads = (
        [
            _clear_intent(),
            [_plan("TASKS", {"task_list_id": "task-list-default"})],
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _write_plan_output(),
            _review_output("PASS"),
        ]
        if graph_profile is GraphProfile.SIX_ROLE_BASELINE
        else [
            _profile_request_source_output(),
            _profile_reason_plan_output("PLAN_READY"),
            _review_output("PASS"),
        ]
    )
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=llm_payloads,
        gateway=gateway,
        checkpoint_database_path=root / "checkpoints-no-write.db",
        graph_profile=graph_profile,
        prompt_manifest_path=manifest_path,
    )

    try:
        started = runtime.start(_start_write_request())
        assert started.outcome is WorkflowOutcome.ACCEPTED
        assert gateway.count_calls("create_task") == 0
        assert gateway.count_calls("update_task") == 0
        assert gateway.count_calls("create_calendar_event") == 0
        assert gateway.count_calls("update_calendar_event") == 0
        assert gateway.count_calls("create_gmail_draft") == 0
        assert gateway.count_calls("update_gmail_draft") == 0
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "graph_profile",
    [
        GraphProfile.SINGLE_BASELINE,
        GraphProfile.THREE_STAGE,
    ],
)
def test_agent_local_checkpoint_is_not_authority_for_approval_or_execution_facts(
    tmp_path: Path,
    graph_profile: GraphProfile,
) -> None:
    root = tmp_path / f"{graph_profile.value.lower()}-checkpoint-authority"
    root.mkdir()
    manifest_path = _runtime_active_manifest_path(root)
    database_path = _seed_runtime_database(root)
    checkpoint_database_path = root / "checkpoints.db"
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _profile_request_source_output(),
            _profile_reason_plan_output("PLAN_READY"),
            _review_output("PASS"),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=checkpoint_database_path,
        graph_profile=graph_profile,
        prompt_manifest_path=manifest_path,
    )

    try:
        started = runtime.start(_start_write_request())
        assert started.outcome is WorkflowOutcome.ACCEPTED

        checkpoint_connection = connect_sqlite(checkpoint_database_path)
        try:
            checkpoint_table_query_prefix = "SELECT name FROM sqlite_master WHERE type = 'table'"
            checkpoint_table_query = (
                f"{checkpoint_table_query_prefix} AND name LIKE 'checkpoints%';"
            )
            checkpoint_tables = [
                row[0] for row in checkpoint_connection.execute(checkpoint_table_query).fetchall()
            ]
            assert checkpoint_tables
            checkpoint_row_count = sum(
                checkpoint_connection.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0]
                for table in checkpoint_tables
            )
            assert checkpoint_row_count > 0
        finally:
            checkpoint_connection.close()

        domain_connection = connect_sqlite(database_path)
        try:
            counts = domain_connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM approvals) AS approval_count,
                    (SELECT COUNT(*) FROM execution_attempts) AS execution_attempt_count,
                    (SELECT COUNT(*) FROM verifications) AS verification_count;
                """
            ).fetchone()
            assert tuple(counts) == (0, 0, 0)
        finally:
            domain_connection.close()
    finally:
        runtime.close()


def test_single_stage_runtime_completes_answer_only_run(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _profile_request_source_output(),
            _profile_reason_plan_output(),
            _review_output("PASS"),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-single-answer.db",
        graph_profile=GraphProfile.SINGLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )

    result = runtime.start(_start_request())

    assert result.outcome is WorkflowOutcome.COMPLETED
    assert result.payload["graph_profile"] == GraphProfile.SINGLE_BASELINE.value
    connection = connect_sqlite(database_path)
    try:
        run_row = connection.execute(
            "SELECT status, version FROM runs WHERE id = 'run-1';"
        ).fetchone()
        plan_count = connection.execute(
            "SELECT COUNT(*) FROM plans WHERE run_id = 'run-1';"
        ).fetchone()[0]
        action_count = connection.execute("SELECT COUNT(*) FROM actions;").fetchone()[0]
        assert tuple(run_row) == ("COMPLETED", 4)
        assert plan_count == 0
        assert action_count == 0
    finally:
        connection.close()
        runtime.close()


def test_three_stage_runtime_completes_answer_only_run(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _profile_request_source_output(),
            _profile_reason_plan_output(),
            _review_output("PASS"),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-three-answer.db",
        graph_profile=GraphProfile.THREE_STAGE,
        prompt_manifest_path=manifest_path,
    )

    result = runtime.start(_start_request())

    assert result.outcome is WorkflowOutcome.COMPLETED
    assert result.payload["graph_profile"] == GraphProfile.THREE_STAGE.value
    connection = connect_sqlite(database_path)
    try:
        run_row = connection.execute(
            "SELECT status, version FROM runs WHERE id = 'run-1';"
        ).fetchone()
        plan_count = connection.execute(
            "SELECT COUNT(*) FROM plans WHERE run_id = 'run-1';"
        ).fetchone()[0]
        action_count = connection.execute("SELECT COUNT(*) FROM actions;").fetchone()[0]
        assert tuple(run_row) == ("COMPLETED", 4)
        assert plan_count == 0
        assert action_count == 0
    finally:
        connection.close()
        runtime.close()


def test_native_three_and_single_profiles_record_expected_invocation_counts(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    three = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _profile_request_source_output(),
            _profile_reason_plan_output(),
            _review_output("PASS"),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-three-native-full.db",
        graph_profile=GraphProfile.THREE_STAGE,
        prompt_manifest_path=manifest_path,
    )
    try:
        three_result = three.start(_start_request())
        three_state = three._graph.get_state(three._config_for_thread("thread-1"))  # noqa: SLF001
        assert three_result.outcome is WorkflowOutcome.COMPLETED
        assert three_state.values["trace_context"]["agent_invocation_count"] == 3
        assert three_state.values["trace_context"]["llm_call_count"] == 3
        assert [
            item["agent_subgraph_id"]
            for item in three_state.values["trace_context"]["agent_node_log"]
            if item["node_name"] == "init"
        ] == ["stage_one", "stage_two", "stage_three"]
    finally:
        three.close()

    single_root = tmp_path / "single-native"
    single_root.mkdir()
    database_path = _seed_runtime_database(single_root)
    single = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _profile_request_source_output(),
            _profile_reason_plan_output(),
            _review_output("PASS"),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=single_root / "checkpoints-single-native-full.db",
        graph_profile=GraphProfile.SINGLE_BASELINE,
        prompt_manifest_path=manifest_path,
    )
    try:
        single_result = single.start(_start_request())
        single_state = single._graph.get_state(single._config_for_thread("thread-1"))  # noqa: SLF001
        assert single_result.outcome is WorkflowOutcome.COMPLETED
        assert single_state.values["trace_context"]["agent_invocation_count"] == 1
        assert single_state.values["trace_context"]["llm_call_count"] == 3
        assert {
            item["agent_subgraph_id"]
            for item in single_state.values["trace_context"]["agent_node_log"]
        } == {"single_workflow"}
    finally:
        single.close()


def test_resume_rejects_profile_change_for_same_thread(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    three_runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[_profile_request_source_output("NEEDS_CONFIRMATION")],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-profile.db",
        graph_profile=GraphProfile.THREE_STAGE,
        prompt_manifest_path=manifest_path,
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
        prompt_manifest_path=manifest_path,
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


@pytest.mark.parametrize(
    ("graph_profile", "root_name"),
    [
        (GraphProfile.SINGLE_BASELINE, "single-plan"),
        (GraphProfile.THREE_STAGE, "three-plan"),
    ],
)
def test_native_profiles_generate_plan_and_share_domain_approval_boundary(
    tmp_path: Path,
    graph_profile: GraphProfile,
    root_name: str,
) -> None:
    root = tmp_path / root_name
    root.mkdir()
    manifest_path = _runtime_active_manifest_path(root)
    database_path = _seed_runtime_database(root)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _profile_request_source_output(),
            _profile_reason_plan_output("PLAN_READY"),
            _review_output("PASS"),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=root / "checkpoints-plan.db",
        graph_profile=graph_profile,
        prompt_manifest_path=manifest_path,
    )

    started = runtime.start(_start_write_request())

    assert started.outcome is WorkflowOutcome.ACCEPTED
    connection = connect_sqlite(database_path)
    try:
        counts = connection.execute(
            """
            SELECT
                (SELECT status FROM runs WHERE id = 'run-1') AS run_status,
                (SELECT COUNT(*) FROM plans WHERE run_id = 'run-1') AS plan_count,
                (SELECT COUNT(*) FROM actions) AS action_count;
            """
        ).fetchone()
        assert tuple(counts) == ("WAITING_APPROVAL", 1, 1)
    finally:
        connection.close()
        runtime.close()


@pytest.mark.parametrize(
    ("graph_profile", "root_name"),
    [
        (GraphProfile.SINGLE_BASELINE, "single-resume"),
        (GraphProfile.THREE_STAGE, "three-resume"),
    ],
)
def test_native_profiles_resume_with_same_profile_after_confirmation(
    tmp_path: Path,
    graph_profile: GraphProfile,
    root_name: str,
) -> None:
    root = tmp_path / root_name
    root.mkdir()
    manifest_path = _runtime_active_manifest_path(root)
    database_path = _seed_runtime_database(root)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    first_runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[_profile_request_source_output("NEEDS_CONFIRMATION")],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=root / "checkpoints-resume.db",
        graph_profile=graph_profile,
        prompt_manifest_path=manifest_path,
    )

    first = first_runtime.start(_start_request())

    assert first.outcome is WorkflowOutcome.ACCEPTED
    first_runtime.close()

    resumed_runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _profile_request_source_output(),
            _profile_reason_plan_output(),
            _review_output("PASS"),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=root / "checkpoints-resume.db",
        graph_profile=graph_profile,
        prompt_manifest_path=manifest_path,
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
                "free_text": "Use the default task list.",
            },
            correlation=WorkflowCorrelationContext(
                request_id="request-2",
                command_id="command-2",
                api_contract_version="1",
            ),
        )
    )

    try:
        assert resumed.outcome is WorkflowOutcome.COMPLETED
    finally:
        resumed_runtime.close()


@pytest.mark.parametrize(
    ("start_profile", "resume_profile", "root_name"),
    [
        (GraphProfile.SINGLE_BASELINE, GraphProfile.THREE_STAGE, "single-to-three"),
        (GraphProfile.SIX_ROLE_BASELINE, GraphProfile.SINGLE_BASELINE, "six-to-single"),
    ],
)
def test_resume_rejects_mismatched_profile_for_thread(
    tmp_path: Path,
    start_profile: GraphProfile,
    resume_profile: GraphProfile,
    root_name: str,
) -> None:
    root = tmp_path / root_name
    root.mkdir()
    manifest_path = _runtime_active_manifest_path(root)
    database_path = _seed_runtime_database(root)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    start_payloads = (
        [_ambiguous_intent()]
        if start_profile is GraphProfile.SIX_ROLE_BASELINE
        else [_profile_request_source_output("NEEDS_CONFIRMATION")]
    )
    starter = _make_runtime(
        database_path=database_path,
        llm_payloads=start_payloads,
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=root / "checkpoints-mismatch.db",
        graph_profile=start_profile,
        prompt_manifest_path=manifest_path,
    )
    first = starter.start(_start_request())
    assert first.outcome is WorkflowOutcome.ACCEPTED
    starter.close()

    resumed_runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=root / "checkpoints-mismatch.db",
        graph_profile=resume_profile,
        prompt_manifest_path=manifest_path,
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
                "free_text": "Continue with the default task list.",
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
        assert resumed.payload["graph_profile"] == resume_profile.value
    finally:
        resumed_runtime.close()


def test_default_product_runtime_rejects_draft_prompt_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    monkeypatch.setenv(
        "GOOGLE_WORK_AGENT_PROMPT_MANIFEST_PATH",
        str(_runtime_active_manifest_path(tmp_path)),
    )

    with pytest.raises(InactivePromptArtifactError, match="request_understanding.classify"):
        _make_runtime(
            database_path=database_path,
            llm_payloads=[],
            gateway=FakeGoogleGateway(snapshot),
            checkpoint_database_path=tmp_path / "checkpoints-draft.db",
        )
