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
    FakeClockPort,
    FakeGoogleGateway,
    GoogleGatewayFault,
    GoogleGatewayFaultKind,
)
from tests.support.fixtures import ProductFixtureSnapshotLoader
from tests.support.prompt_manifests import (
    write_draft_manifest,
    write_manifest_with_legacy_profile_slots,
    write_manifest_with_overrides,
    write_runtime_active_manifest,
)
from tests.unit.application.workflows.test_api_acquisition import _plan
from tests.unit.application.workflows.test_context_retrieval import _sufficiency_output
from tests.unit.application.workflows.test_plan_review import _review_output

from google_work_agent.adapters.connectors.runtime.mcp_connector_write import (
    McpConnectorWriteAdapter,
)
from google_work_agent.adapters.langgraph.main.workflow import LangGraphWorkflowRuntime
from google_work_agent.adapters.langgraph.profiles import (
    GraphProfile,
    supported_graph_profiles,
)
from google_work_agent.adapters.persistence import (
    apply_migrations,
    connect_sqlite,
    sqlite_unit_of_work_factory,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    ActionPlanDraftV1,
    AnswerDraftV1,
    ContextRetrievalResultV1,
    EvidenceDraftV1,
    EvidenceSelectionResultV2,
    RequestIntentV2,
    RetrievalResultV1,
    WorkAnalysisResultV1,
)
from google_work_agent.application.orchestration.prompt_registry import InactivePromptArtifactError
from google_work_agent.application.orchestration.provider_dispatch_budget import (
    account_provider_dispatch,
)
from google_work_agent.application.orchestration.tool_routing import (
    coarse_resource_category,
    determine_semantic_routes,
)
from google_work_agent.application.orchestration.work_analysis import (
    validate_work_analysis_result_v1,
)
from google_work_agent.application.write_action_mutation import (
    ModifyWriteActionService,
    RejectWriteActionService,
)
from google_work_agent.application.write_action_mutation_contracts import (
    ModifyWriteActionCommand,
    RejectWriteActionCommand,
)
from google_work_agent.application.write_approval import ApproveWriteActionService
from google_work_agent.application.write_approval_contracts import (
    ApproveWriteActionCommand,
)
from google_work_agent.application.write_execution_contracts import (
    ClaimWriteActionCommand,
    StoreWriteActionSuccessCommand,
)
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
from google_work_agent.ports.connector.migration_contracts.tool_registry import (
    ConnectorToolCatalog,
    build_p0_tool_registry,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "product"
_SYNTHESIZE_RETRIEVAL_QUERY_PLAN = object()
_RUNTIME_ACTIVE_PROMPT_IDS = {
    "request_understanding.classify",
    "tool_route.determine_io_resources",
    "tool_route.determine_io_resources.revise",
    "tool_route.select_tool_if_needed",
    "tool_route.select_tool_if_needed.revise",
    "retrieval.plan_query",
    "retrieval.plan_query.revise",
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
_PROFILE_CANDIDATE_PROMPT_IDS = {
    "profile.single.request_source.initial",
    "profile.single.reason_plan.initial",
    "profile.single.self_review.initial",
    "profile.single.self_review.recheck",
    "profile.three.stage1.initial",
    "profile.three.stage2.initial",
}
# SINGLE_BASELINE/THREE_STAGE profile prompts ("profile.single.*",
# "profile.three.*") and "request_understanding.clarify" have no
# slot in prompt-manifest-v0.9.1.json -- the runtime-closure bundle only
# ships the SIX_ROLE_BASELINE-role prompts above. Tests that construct those
# profiles fail closed on InactivePromptArtifactError/LookupError until
# Prompt Authoring ships matching artifacts for them; that is a
# Prompt Artifact gap, not something this integration pass can invent.


def _tool_catalog() -> ConnectorToolCatalog:
    catalog = ConnectorToolCatalog()
    catalog.register(connector_id="google_workspace", registry=build_p0_tool_registry())
    return catalog


class _PendingPlanActionsState:
    """Mutable box for the canonical-writer-synthesis carry-over state.

    Shared (via composition, not inheritance) between ``_QueuedLLMRuntime``
    and any other test LLM double that needs the same
    ``planning.compose_arguments``/``.revise`` -> per-route
    ``ToolArgumentCandidateV1`` synthesis (see
    ``_synthesize_action_argument_candidate`` below) without duplicating its
    ~35 lines of logic.
    """

    def __init__(self) -> None:
        self.pending: list[dict[str, object]] | None = None


def _synthesize_action_argument_candidate(
    queued: "deque[StructuredLLMResult]",
    state: _PendingPlanActionsState,
    *,
    route_id: str,
    tool_id: str,
    effect: str,
) -> dict[str, object]:
    """Synthesize one canonical ``ToolArgumentCandidateV1`` from a queued
    legacy whole-plan ``ActionPlanDraftV1`` payload's matching action.

    Canonical ACTION Planning calls the per-route Argument Writer once per
    frozen output route instead of one whole-plan generation call. These
    ~50 pre-existing fixtures still queue a single legacy whole-plan
    payload (authored before that migration) -- this synthesizes each
    route's thin candidate from that same queued plan's matching action
    instead of asking every fixture to be rewritten.
    """

    if state.pending is None:
        if not queued:
            raise RuntimeError("no queued llm result")
        payload = queued.popleft().structured_output
        if not (isinstance(payload, Mapping) and isinstance(payload.get("actions"), list)):
            raise RuntimeError(
                "planning.compose_arguments expects a legacy whole-plan "
                "ActionPlanDraftV1 payload (with an 'actions' list) at the "
                f"front of the queue to synthesize a canonical "
                f"ToolArgumentCandidateV1 from; got {payload!r}"
            )
        state.pending = [dict(action) for action in payload["actions"]]
    matches = [
        action
        for action in state.pending
        if action.get("tool_name") == tool_id and action.get("effect") == effect
    ]
    if not matches:
        raise RuntimeError(
            f"no queued whole-plan action matches frozen route tool={tool_id!r} "
            f"effect={effect!r}; remaining queued actions: {state.pending!r}"
        )
    action = matches[0]
    state.pending.remove(action)
    if not state.pending:
        state.pending = None
    return {
        "schema_version": 1,
        "route_id": route_id,
        "arguments": dict(cast(Mapping[str, object], action["arguments"])),
        "evidence_refs": list(cast("list[str]", action["evidence_refs"])),
    }


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
        self._pending_plan_actions_state = _PendingPlanActionsState()

    def invoke_structured(self, **kwargs: object) -> StructuredLLMResult:
        return self._invoke(**kwargs)

    def invoke_tool_call(self, **kwargs: object) -> StructuredLLMResult:
        return self._invoke(**kwargs)

    def discard_run(self, *, run_id: str) -> None:
        del run_id

    def _invoke(self, **kwargs: object) -> StructuredLLMResult:
        if self._before_invoke is not None:
            self._before_invoke()
        account_provider_dispatch()
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
        if getattr(prompt_ref, "prompt_id", None) == "retrieval.plan_query":
            prompt_input = cast(Mapping[str, object], kwargs["prompt_input"])
            # Retrieval V2's INITIAL plan_query call also has no
            # fixture-authored payload in these ~50 pre-existing tests --
            # they predate the Tool Route -> Retrieval V2 topology and were
            # written against an older acquisition.plan_sources-first flow.
            # Synthesize a structurally valid INITIAL SEARCH plan over
            # whatever routes Tool Route actually froze, same rationale as
            # the tool_route.determine_io_resources synthesis above: these
            # tests control their actual semantic outcome via the queued
            # select_evidence/assess_sufficiency payloads, not via
            # plan_query's content. Only INITIAL is synthesized -- a
            # follow-up (CHANGED search) call still consumes the queue
            # normally, so tests that intentionally queue one keep working.
            # ``load_acquisition_plan_sources_prompt_reference`` (the
            # legacy Source Planning agent) resolves the very same
            # "retrieval.plan_query" slot id with an identically-shaped
            # prompt_input (request_intent/input_routes/retrieval_budget),
            # so neither prompt_id nor prompt_input alone can distinguish
            # the two callers. Their output_schema differs though --
            # RetrievalQueryPlannerAgent uses
            # RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA ("retrieval-query-plan-v2"),
            # legacy plan_sources uses SOURCE_FETCH_PLAN_OUTPUT_SCHEMA
            # ("source-fetch-plan-v2-list") -- a bare prompt_id match would
            # wrongly intercept the legacy call too and feed it a
            # RetrievalQueryPlanV2 dict instead of the SourceFetchPlanV1
            # list it actually expects.
            output_schema = kwargs.get("output_schema")
            schema_version = getattr(output_schema, "schema_version", None)
            is_v2_plan_call = schema_version == "retrieval-query-plan-v2"
            if is_v2_plan_call and "current_round_no" not in prompt_input:
                return _llm_result(_synthesize_retrieval_query_plan(prompt_input))
            if (
                is_v2_plan_call
                and self._queued
                and self._queued[0].structured_output is _SYNTHESIZE_RETRIEVAL_QUERY_PLAN
            ):
                self._queued.popleft()
                return _llm_result(_synthesize_retrieval_query_plan(prompt_input))
        if getattr(prompt_ref, "prompt_id", None) == "planning.compose_arguments":
            prompt_input = cast(Mapping[str, object], kwargs["prompt_input"])
            output_route = cast(Mapping[str, object], prompt_input["output_route"])
            return _llm_result(
                _synthesize_action_argument_candidate(
                    self._queued,
                    self._pending_plan_actions_state,
                    route_id=cast(str, output_route["route_id"]),
                    tool_id=cast(str, output_route["selected_tool_id"]),
                    effect=cast(str, output_route["effect"]),
                )
            )
        if getattr(prompt_ref, "prompt_id", None) == "planning.compose_arguments.revise":
            prompt_input = cast(Mapping[str, object], kwargs["prompt_input"])
            base_projection = cast(Mapping[str, object], prompt_input["base_projection"])
            output_route = cast(Mapping[str, object], base_projection["output_route"])
            candidate_output = cast(Mapping[str, object], prompt_input["candidate_output"])
            return _llm_result(
                _synthesize_action_argument_candidate(
                    self._queued,
                    self._pending_plan_actions_state,
                    route_id=cast(str, candidate_output["route_id"]),
                    tool_id=cast(str, output_route["selected_tool_id"]),
                    effect=cast(str, output_route["effect"]),
                )
            )
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


def _synthesize_retrieval_query_plan(prompt_input: Mapping[str, object]) -> dict[str, object]:
    """Fake response for retrieval.plan_query's INITIAL round.

    A structurally valid RetrievalQueryPlanV2 SEARCH over every route Tool
    Route actually froze -- see the synthesis rationale next to its call
    site in ``_QueuedLLMRuntime._invoke``. The constraint kind is picked per
    coarse resource_type since each resource_type has its own
    RouteConstraintPolicy.supported_kinds (context_retrieval.py's
    ``_runtime_route_constraint_policies``). TASK routes only support
    CONTAINER_REF, which real production code can never actually validate
    today unless the runtime was constructed with a
    ``default_tasklist_id_provider`` (Pre-Prompt Runtime Closure --
    ``_validated_task_container_refs`` in context_retrieval.py): when the
    caller configured one, each TASK route's projected ``input_routes``
    entry now carries a real, already-validated ``container_refs`` list
    (see ``_prompt_route`` in retrieval_planner_input.py), which this fake
    echoes back verbatim -- exactly what a real planner LLM would do,
    never inventing its own container id. Without a configured provider, a
    TASK route still gets a best-effort placeholder CONTAINER_REF
    constraint so it fails with the same, correctly-diagnosed validation
    error rather than a confusing unrelated one from misaligning the rest
    of the fixture's queue.
    """
    input_routes = cast(list[dict[str, object]], prompt_input["input_routes"])
    route_ids = [route["route_id"] for route in input_routes]

    def _constraint(route: dict[str, object]) -> dict[str, object]:
        # ``route["resource_type"]`` here is already the prompt-facing
        # coarse EMAIL/TASK/CALENDAR value (``_prompt_route`` in
        # retrieval_planner_input.py already coarsens it) -- it must be
        # compared directly, not re-coarsened, since ``coarse_resource_category``
        # only accepts fine-grained Registry types (e.g. "GMAIL_THREAD") and
        # raises for an already-coarse "EMAIL".
        resource_type = route.get("resource_type")
        if resource_type == "CALENDAR":
            return {
                "kind": "TEMPORAL_RANGE",
                "axis": "EVENT_TIME",
                "start_local": "2026-11-01T00:00:00",
                "end_local": "2026-11-02T00:00:00",
                "timezone": "UTC",
            }
        if resource_type == "TASK":
            container_refs = route.get("container_refs") or ["synthesized-container"]
            return {"kind": "CONTAINER_REF", "container_refs": container_refs}
        # FakeGoogleGateway.search_gmail_threads special-cases this exact
        # query as "match everything in the default fixture inbox" -- a
        # synthesized EMAIL SEARCH constraint value shouldn't assume any
        # particular fixture participant/subject content is present.
        return {"kind": "KEYWORD", "terms": ["in:inbox category:primary"], "match_mode": "ANY"}

    return {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": route["route_id"],
                "operation": "SEARCH",
                "reason_codes": ["REQUIRED"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [_constraint(route)],
                },
                "detail_candidate_ref": None,
            }
            for route in input_routes
        ],
        "required_information": ["synthesized-initial-search"],
        "retrieval_order": route_ids,
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
                "evidence_refs": ["evidence-seg-2"],
                "resource_refs": ["task:task-followup"],
                "segment_refs": ["seg-2"],
                "related_resource_handles": ["task:task-followup"],
                "reason_codes": ["EVIDENCE_SUPPORTED"],
            }
        ],
        "missing_information": [],
        "confirmation": None,
        "blockers": [],
        "evidence_refs": ["evidence-seg-2"],
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
        "evidence_refs": ["evidence-seg-2"],
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
    # ``resource_id`` is server-assigned on CREATE and was never a valid
    # ``tasks_create_task`` argument (``_TASK_CREATE_PAYLOAD`` has
    # ``additionalProperties: False`` and no ``resource_id`` property) --
    # ``_expected_task_projection`` already takes it as its own explicit
    # kwarg below. The canonical Argument Writer's fail-closed schema check
    # (T4) now correctly rejects it if it stays inside the arguments
    # payload; legacy validation never checked ``additionalProperties``.
    payload = {
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
                "evidence_refs": ["evidence-seg-2"],
                "resource_refs": ["task:task-followup"],
                "target_resource_ref_id": None,
                "depends_on_action_ids": [],
                "user_visible_reason": "Create the requested follow-up task.",
            }
        ],
        "evidence_refs": ["evidence-seg-2"],
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
            "evidence_refs": ["evidence-seg-3"],
            "resource_refs": ["gmail_message:message-project-1"],
            "user_visible_reason": "Send the approved Gmail draft.",
        }
    )
    plan["summary"] = "Send the approved Gmail draft requested by the user."
    plan["evidence_refs"] = ["evidence-seg-3"]
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
            "evidence_refs": ["evidence-seg-1"],
            "resource_refs": ["calendar_event:event-focus"],
            "target_resource_ref_id": "calendar_event:event-focus",
            "user_visible_reason": "Delete the approved single calendar event.",
        }
    )
    plan["summary"] = "Delete the approved single calendar event requested by the user."
    plan["evidence_refs"] = ["evidence-seg-1"]
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


def _selection_output() -> EvidenceSelectionResultV2:
    return {
        "schema_version": 2,
        "selected_segment_ids": ["seg-2"],
        "evidence_drafts": [
            {
                "segment_id": "seg-2",
                "role": "SUPPORTS",
                "relevance_reason": "Reply to project sync",
            }
        ],
        "excluded_segment_ids": [],
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
            "evidence_refs": ["evidence-seg-2"],
            "normalized_context": [],
            "missing_information": [],
            "ambiguity": None,
        },
        "evidence_drafts": [
            {
                "schema_version": 1,
                "evidence_id": "evidence-seg-2",
                "resource_handle": "task:task-followup",
                "segment_id": "seg-2",
                "kind": "excerpt",
                "excerpt": "Reply to project sync",
                "locator": {"kind": "resource_payload"},
                "reason_codes": ["SUPPORTS"],
            }
        ],
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


def _evidence_drafts_seg_2() -> list[EvidenceDraftV1]:
    """The one evidence draft ``_retrieval_result()`` references -- same
    seg-2/evidence-seg-2/task:task-followup reference space as
    ``_context_result()``, so callers using both stay consistent."""
    return [
        {
            "schema_version": 1,
            "evidence_id": "evidence-seg-2",
            "resource_handle": "task:task-followup",
            "segment_id": "seg-2",
            "kind": "excerpt",
            "excerpt": "Reply to project sync",
            "locator": {"kind": "resource_payload"},
            "reason_codes": ["SUPPORTS"],
        }
    ]


def _retrieval_result(
    coverage: Literal["SUFFICIENT", "PARTIAL", "NO_FETCH_NEEDED"] = "SUFFICIENT",
) -> RetrievalResultV1:
    """Canonical Retrieval->Parent handoff (06-agent-workflow.md SS3.3).

    Callers must also seed the run's ``RunScopedEvidenceStore`` with
    ``_evidence_drafts_seg_2()`` before invoking a node that resolves this
    result's ``evidence_refs`` (e.g. ``runtime._evidence_store.put(run_id=...,
    evidence_drafts=_evidence_drafts_seg_2())``) -- this handoff type only
    carries references, never materialized evidence.
    """
    return {
        "schema_version": 1,
        "meta": {"artifact_id": "retrieval-1", "revision": 1, "based_on": []},
        "coverage": coverage,
        "context_bundle_ref": None,
        "evidence_refs": ["evidence-seg-2"],
        "selected_segment_ids": ["seg-2"],
        "source_resource_refs": ["task:task-followup"],
        "source_statuses": [],
        "missing_information": [],
        "retrieval_rounds": 1,
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


def _calendar_selection_output() -> EvidenceSelectionResultV2:
    return {
        "schema_version": 2,
        "selected_segment_ids": ["seg-1"],
        "evidence_drafts": [
            {
                "segment_id": "seg-1",
                "role": "SUPPORTS",
                "relevance_reason": "Focus block",
            }
        ],
        "excluded_segment_ids": [],
    }


def _calendar_analysis_output() -> dict[str, object]:
    result = _validated_analysis_result()
    finding = result["findings"][0]
    finding["evidence_refs"] = ["evidence-seg-1"]
    finding["resource_refs"] = ["calendar_event:event-focus"]
    finding["related_resource_handles"] = ["calendar_event:event-focus"]
    finding["segment_refs"] = ["seg-1"]
    result["evidence_refs"] = ["evidence-seg-1"]
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


def _gmail_selection_output() -> EvidenceSelectionResultV2:
    return {
        "schema_version": 2,
        "selected_segment_ids": ["seg-3"],
        "evidence_drafts": [
            {
                "segment_id": "seg-3",
                "role": "SUPPORTS",
                "relevance_reason": "Please summarize the open items and draft a calm reply.",
            }
        ],
        "excluded_segment_ids": [],
    }


def _gmail_analysis_output() -> dict[str, object]:
    result = _validated_analysis_result()
    finding = result["findings"][0]
    finding["evidence_refs"] = ["evidence-seg-3"]
    finding["resource_refs"] = ["gmail_message:message-project-1"]
    finding["related_resource_handles"] = ["gmail_message:message-project-1"]
    finding["segment_refs"] = ["seg-3"]
    result["evidence_refs"] = ["evidence-seg-3"]
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


def _profile_request_source_output(
    result: str = "PLAN_READY",
    *,
    request_intent: RequestIntentV2 | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 2,
        "request_intent": request_intent or _clear_intent(),
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
    checkpoint_database_path: Path | None = None,
    checkpoint_port=None,
    graph_profile: GraphProfile = GraphProfile.SIX_ROLE_BASELINE,
    prompt_manifest_path: Path | None = None,
    before_llm_invoke: Callable[[], None] | None = None,
    default_tasklist_id: str | None = "task-list-default",
    default_calendar_id: str | None = "calendar-primary",
    id_prefix: str = "runtime",
) -> LangGraphWorkflowRuntime:
    clock = FakeClockPort(1000)
    ids = DeterministicUUID(prefix=id_prefix)
    return LangGraphWorkflowRuntime(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        llm_runtime=_QueuedLLMRuntime(llm_payloads, before_invoke=before_llm_invoke),
        gateway=gateway,
        connector_execution=McpConnectorWriteAdapter(gateway=gateway),
        tool_catalog=_tool_catalog(),
        now_ms=clock.now_ms,
        id_factory=ids.next_id,
        signing_secret="stage17-secret",
        service_instance_id="stage17-service",
        checkpoint_database_path=checkpoint_database_path,
        checkpoint_port=checkpoint_port,
        graph_profile=graph_profile,
        prompt_manifest_path=prompt_manifest_path,
        default_tasklist_id_provider=(
            None if default_tasklist_id is None else (lambda: default_tasklist_id)
        ),
        default_calendar_id_provider=(
            None if default_calendar_id is None else (lambda: default_calendar_id)
        ),
    )


def _sole_persisted_action_id(database_path: Path, *, run_id: str = "run-1") -> str:
    """The single write action's real, assembler-generated id.

    These ~50 pre-existing fixtures were authored when Planning's own LLM
    output supplied a literal ``action_id`` (e.g. ``"action-1"``) verbatim
    through to persistence. Canonical Planning's ``PlanAssembler`` now owns
    Action ID generation deterministically (via the runtime's shared
    ``id_factory``) instead of trusting the LLM candidate, so tests must
    look the real id up rather than assume a literal string.
    """
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            """
            SELECT actions.id FROM actions
            JOIN plans ON plans.id = actions.plan_id
            WHERE plans.run_id = ?
            ORDER BY plans.revision_no DESC, actions.position ASC
            LIMIT 1;
            """,
            (run_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise AssertionError(f"no persisted action found for run_id={run_id!r}")
    return cast(str, row[0])


def _sole_persisted_plan_id(database_path: Path, *, run_id: str = "run-1") -> str:
    """The current (latest-revision) plan's real, assembler-generated id.

    Same rationale as ``_sole_persisted_action_id`` -- canonical Planning's
    ``PlanAssembler`` owns Plan ID generation via the shared ``id_factory``
    for a fresh plan (a revision reuses the previous plan's id instead), so
    tests must look the real id up rather than assume a literal
    ``"plan-1"``.
    """
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            """
            SELECT id FROM plans WHERE run_id = ?
            ORDER BY revision_no DESC
            LIMIT 1;
            """,
            (run_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise AssertionError(f"no persisted plan found for run_id={run_id!r}")
    return cast(str, row[0])


def _runtime_active_manifest_path(tmp_path: Path) -> Path:
    return write_manifest_with_legacy_profile_slots(
        tmp_path,
        legacy_prompt_ids=_PROFILE_CANDIDATE_PROMPT_IDS,
        active_prompt_ids=_RUNTIME_ACTIVE_PROMPT_IDS,
        draft_prompt_ids=(),
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


_SIX_ROLE_BASELINE_PROMPT_IDS = {
    # request_understanding.clarify is intentionally absent: it is
    # compatibility-only, never wired into the active SIX_ROLE_BASELINE
    # subgraph node, and correctly has no slot in the canonical manifest.
    "request_understanding.classify",
    "tool_route.determine_io_resources",
    "tool_route.determine_io_resources.revise",
    "tool_route.select_tool_if_needed",
    "tool_route.select_tool_if_needed.revise",
    "retrieval.plan_query",
    "retrieval.plan_query.revise",
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
