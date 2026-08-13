"""Shared LangGraph runtime integration fixtures and compatibility exports."""

# ruff: noqa: F401

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Literal, cast

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
from tests.support.prompt_manifests import (
    write_draft_manifest,
    write_manifest_with_overrides,
    write_runtime_active_manifest,
)
from tests.unit.application.workflows.test_api_acquisition import _plan
from tests.unit.application.workflows.test_context_retrieval import _sufficiency_output
from tests.unit.application.workflows.test_plan_review import _review_output

from google_work_agent.adapters.connectors import GoogleWorkspaceExecutionBackend
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
    ModifyWriteActionCommand,
    ModifyWriteActionService,
    RejectWriteActionCommand,
    RejectWriteActionService,
    StoreWriteActionSuccessCommand,
)
from google_work_agent.application.workflows import (
    ActionPlanDraftV1,
    AnswerDraftV1,
    ContextRetrievalResultV1,
    EvidenceSelectionOutputV1,
    RequestIntentV2,
    WorkAnalysisResultV1,
    determine_semantic_routes,
    validate_work_analysis_result_v1,
)
from google_work_agent.application.workflows.prompt_registry import InactivePromptArtifactError
from google_work_agent.application.workflows.tool_routing import coarse_resource_category
from google_work_agent.domain import ConnectorToolCatalog, build_p0_tool_registry
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
    "tool_route.determine_io_resources",
    "tool_route.select_tool_if_needed",
    "retrieval.plan_query",
    "retrieval.select_evidence",
    "retrieval.select_evidence.revise",
    "retrieval.assess_sufficiency",
    "work_analysis.analyze",
    "planning.compose_answer",
    "planning.compose_arguments",
    "planning.compose_arguments.revise",
    "planning.compose_answer.revise",
    "review.inspect",
    "review.inspect.recheck",
}
# SINGLE_BASELINE/THREE_STAGE profile prompts ("profile.single.*",
# "profile.three.*") and "request_understanding.clarify" have no v0.9.0
# slot in prompt-manifest-v0.9.0.json -- the PHASE 7.5 bundle only ships
# the SIX_ROLE_BASELINE-role prompts above. Tests that construct those
# profiles fail closed on InactivePromptArtifactError/LookupError until
# Prompt Authoring ships matching PHASE 7.5 artifacts for them; that is a
# Prompt Artifact gap, not something this integration pass can invent.


def _tool_catalog() -> ConnectorToolCatalog:
    catalog = ConnectorToolCatalog()
    catalog.register(connector_id="google_workspace", registry=build_p0_tool_registry())
    return catalog


class _QueuedLLMRuntime:
    def __init__(
        self,
        payloads: Sequence[object],
        *,
        before_invoke: Callable[[], None] | None = None,
    ) -> None:
        self._queued = deque(_llm_result(item) for item in payloads)
        self.calls: list[dict[str, object]] = []
        self._before_invoke = before_invoke

    def invoke_structured(self, **kwargs: object) -> StructuredLLMResult:
        return self._invoke(**kwargs)

    def invoke_tool_call(self, **kwargs: object) -> StructuredLLMResult:
        return self._invoke(**kwargs)

    def _invoke(self, **kwargs: object) -> StructuredLLMResult:
        if self._before_invoke is not None:
            self._before_invoke()
        self.calls.append(dict(kwargs))
        prompt_ref = kwargs.get("prompt_ref")
        if getattr(prompt_ref, "prompt_id", None) == "tool_route.determine_io_resources":
            # Tool Route's semantic LLM call has no fixture-authored payload
            # in these tests -- it is synthesized here from the same
            # request_intent every other queued payload was authored
            # against, so the resulting ToolRoutePlanV2 (and everything
            # every existing test asserts about it) is unchanged. This
            # keeps the ~50 pre-existing llm_payloads=[...] fixtures in this
            # suite from needing an inserted entry for a call they were
            # never written to expect.
            prompt_input = cast(Mapping[str, object], kwargs["prompt_input"])
            request_intent = cast(RequestIntentV2, prompt_input["request_intent"])
            return _llm_result(_synthesize_tool_route_candidate(request_intent))
        if not self._queued:
            raise RuntimeError("no queued llm result")
        return self._queued.popleft()


def _synthesize_tool_route_candidate(request_intent: RequestIntentV2) -> dict[str, object]:
    """Fake response for tool_route.determine_io_resources.

    Mirrors what ``determine_semantic_routes`` (the deterministic
    compatibility path Tool Route falls back to without an LLM candidate)
    derives from the same request_intent, so the resulting ToolRoutePlanV2
    is identical to what these tests were originally written against.
    Raises ToolRouteValidationError the same way determine_semantic_routes
    does for an unsupported hint combination -- ToolRouteCoordinator.route()
    already catches that from its semantic_candidate_provider and reports
    NEEDS_CONFIRMATION, so ambiguous-intent test cases are unaffected.
    """

    candidate = determine_semantic_routes(request_intent)
    return {
        "schema_version": 1,
        "input_resource_types": sorted(
            {coarse_resource_category(item) for item in candidate.input_resource_types}
        ),
        "output_resource_types": sorted(
            {coarse_resource_category(resource) for resource, _effect in candidate.output_pairs}
        ),
        "output_effects": [effect.value for _resource, effect in candidate.output_pairs],
        "disposition": "ROUTE_READY",
    }


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


def _clear_intent() -> RequestIntentV2:
    # No "meta": these fixtures double as raw request_understanding.classify
    # LLM candidates (fed through validate_request_intent_v2, whose input
    # schema forbids "meta" -- Application attaches it afterward) as well as
    # stand-ins for an already-materialized state["request_intent"]. cast
    # mirrors validate_request_intent_v2's own two-phase-construction
    # return statement in request_understanding.py.
    return cast(
        RequestIntentV2,
        {
            "schema_version": 2,
            "goal": "Resolve the user's Google Workspace request.",
            "completion_conditions": ["Return a useful answer or plan."],
            "constraints": [
                {"kind": "PERSON", "field": "person", "value": "Kim"},
            ],
            "ambiguity": {
                "requires_confirmation": False,
                "reason_codes": [],
                "missing_fields": [],
            },
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["TASK"],
            "analysis_requirement": "REQUIRED",
        },
    )


def _action_required_intent() -> RequestIntentV2:
    payload = _clear_intent()
    payload["requested_effect_hints"] = ["CREATE"]
    payload["requested_resource_hints"] = ["TASK"]
    return payload


def _action_intent(
    *,
    resource: str,
    effect: str,
    source: Literal["GMAIL", "TASKS", "CALENDAR"] = "TASKS",
) -> RequestIntentV2:
    """``source`` selects which context family the caller should acquire
    retrieval context from (see ``_plan``/``_selection_output`` pairing in
    call sites) -- RequestIntentV2 has no field for it; it is not written
    into the returned intent."""
    del source
    payload = _action_required_intent()
    payload["requested_resource_hints"] = [resource]
    payload["requested_effect_hints"] = cast(
        "list[Literal['READ', 'CREATE', 'UPDATE', 'SEND', 'DELETE']]", [effect]
    )
    return payload


def _ambiguous_intent() -> RequestIntentV2:
    payload = _clear_intent()
    payload["ambiguity"] = {
        "requires_confirmation": True,
        "reason_codes": ["INTENT_AMBIGUITY_MISSED"],
        "missing_fields": ["대상 인물"],
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


def _validated_analysis_result() -> WorkAnalysisResultV1:
    return validate_work_analysis_result_v1(
        _analysis_output(),
        context_result=_context_result(),
    )


def _answer_output() -> AnswerDraftV1:
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


def _write_plan_output() -> ActionPlanDraftV1:
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


def _send_write_plan_output() -> ActionPlanDraftV1:
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
            "resource_refs": ["gmail_message:message-project-1"],
            "user_visible_reason": "Send the approved Gmail draft.",
        }
    )
    plan["summary"] = "Send the approved Gmail draft requested by the user."
    plan["resource_refs"] = [
        {
            "resource_handle": "gmail_message:message-project-1",
            "resource_type": "gmail_message",
            "resource_id": "message-project-1",
        }
    ]
    return plan


def _delete_write_plan_output() -> ActionPlanDraftV1:
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


def _delete_task_write_plan_output() -> ActionPlanDraftV1:
    plan = _write_plan_output()
    action = plan["actions"][0]
    action.update(
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
            "user_visible_reason": "Delete the approved follow-up task.",
        }
    )
    plan["summary"] = "Delete the approved follow-up task requested by the user."
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


def _selection_output() -> EvidenceSelectionOutputV1:
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


def _context_result(
    status: Literal[
        "SUFFICIENT", "NEEDS_MORE_DATA", "NEEDS_CONFIRMATION", "PARTIAL", "BLOCKED"
    ] = "SUFFICIENT",
) -> ContextRetrievalResultV1:
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


def _calendar_selection_output() -> EvidenceSelectionOutputV1:
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
    result = _validated_analysis_result()
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
    payload: dict[str, object] = dict(result)
    payload.pop("additional_acquisition_request")
    return payload


def _gmail_selection_output() -> EvidenceSelectionOutputV1:
    return {
        "schema_version": 1,
        "result": "SELECTED",
        "selected_segment_ids": ["seg-3"],
        "evidence_drafts": [
            {
                "schema_version": 1,
                "evidence_id": "evidence-1",
                "resource_handle": "gmail_message:message-project-1",
                "segment_id": "seg-3",
                "kind": "excerpt",
                "excerpt": "Please summarize the open items and draft a calm reply.",
                "locator": {"kind": "resource_payload"},
                "reason_codes": ["GOAL_RELEVANT"],
            }
        ],
        "excluded_resource_handles": [],
        "missing_information": [],
        "ambiguity": None,
    }


def _gmail_analysis_output() -> dict[str, object]:
    result = _validated_analysis_result()
    finding = result["findings"][0]
    finding["resource_refs"] = ["gmail_message:message-project-1"]
    finding["related_resource_handles"] = ["gmail_message:message-project-1"]
    finding["segment_refs"] = ["seg-3"]
    result["resource_refs"] = [
        {
            "resource_handle": "gmail_message:message-project-1",
            "resource_type": "gmail_message",
            "resource_id": "message-project-1",
        }
    ]
    result["segment_refs"] = [
        {"segment_id": "seg-3", "resource_handle": "gmail_message:message-project-1"}
    ]
    payload: dict[str, object] = dict(result)
    payload.pop("additional_acquisition_request")
    return payload


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
    llm_payloads: Sequence[object],
    gateway: FakeGoogleGateway,
    checkpoint_database_path: Path,
    graph_profile: GraphProfile = GraphProfile.SIX_ROLE_BASELINE,
    prompt_manifest_path: Path | None = None,
    before_llm_invoke: Callable[[], None] | None = None,
) -> LangGraphWorkflowRuntime:
    clock = FakeClock(1000)
    ids = DeterministicUUID(prefix="runtime")
    return LangGraphWorkflowRuntime(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        llm_runtime=_QueuedLLMRuntime(llm_payloads, before_invoke=before_llm_invoke),
        gateway=gateway,
        connector_execution=GoogleWorkspaceExecutionBackend(gateway=gateway),
        tool_catalog=_tool_catalog(),
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


_SIX_ROLE_BASELINE_PROMPT_IDS = {
    "request_understanding.classify",
    "request_understanding.clarify",
    "acquisition.plan_sources",
    "context.select_evidence",
    "context.select_evidence.semantic_revision",
    "context.assess_sufficiency",
    "analysis.analyze",
    "planning.answer_only",
    "planning.draft_plan",
    "planning.revise_plan",
    "planning.revise_answer",
    "review.inspect",
    "review.recheck",
}
_PROFILE_CANDIDATE_PROMPT_IDS = {
    "profile.single.request_source.initial",
    "profile.single.reason_plan.initial",
    "profile.single.self_review.initial",
    "profile.single.self_review.recheck",
    "profile.three.stage1.initial",
    "profile.three.stage2.initial",
}


# GAP-F1 (Q2-X update): requested_effect_hints (RequestIntentV2), not a
# keyword scan over request_text, decides the SIX_ROLE_BASELINE Planning
# subgraph's mode -- a write effect (CREATE/UPDATE/SEND/DELETE) means
# draft_plan, otherwise answer_only. The case names below still carry the
# request_text that motivated them, but the assertions in
# test_runtime_state_boundaries.py are driven purely by the constructed
# intent's effect hints, including cases whose request_text carries an old
# trigger word ("delete"/"list") paired with the opposite hint, to prove
# request_text is no longer consulted at all.
_ANSWER_ONLY_SEMANTIC_CASES: tuple[tuple[str, str], ...] = (
    ("korean-schedule-lookup", "오늘 일정 알려줘"),
    ("korean-incomplete-tasks-summary", "미완료 업무 정리해줘. 새 항목은 만들지 마."),
    ("korean-recent-project-mail-summary", "최근 프로젝트 관련 메일 요약해줘"),
    ("trigger-word-trap", "Please list and delete nothing, just tell me what's going on."),
)
_ACTION_REQUIRED_SEMANTIC_CASES: tuple[tuple[str, str], ...] = (
    ("korean-draft-reply", "이 메일에 답장 초안 만들어줘"),
    ("korean-create-report-task", "내일 보고서 작성 할 일 만들어줘"),
    ("korean-schedule-work-block", "내일 오후에 작업 일정 잡아줘"),
    ("korean-delete-task", "이 할 일 삭제해줘"),
    ("english-draft-reply", "Draft a reply to this email."),
    ("english-create-task", "Create a task for tomorrow."),
    ("english-schedule-work-block", "Schedule a work block tomorrow afternoon."),
    ("english-delete-task", "Delete this task."),
    ("no-trigger-word-trap", "Please make sure this happens by end of day tomorrow."),
)


def _planning_mode_runtime(tmp_path: Path) -> LangGraphWorkflowRuntime:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    return _make_runtime(
        database_path=database_path,
        llm_payloads=[],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=tmp_path / "checkpoints-planning-mode.db",
        prompt_manifest_path=manifest_path,
    )
