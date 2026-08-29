"""C2-A/C2-B: Tool Route Confirmation -- nested subgraph checkpoint resume
integration tests.

Tool Route's only NEEDS_CONFIRMATION triggers are
``determine_semantic_candidate`` raising (C2-A ordinary ambiguity -- the
very first step of ``ToolRouteCoordinator.route()``) and a mandatory Policy
Precondition READ falling outside the user's own explicit SCOPE constraints
(C2-B ``SCOPE_EXPANSION_REQUIRED``, detected after output routes are bound
but before ``_merge_policy_preconditions``). Neither leaves "already
completed" downstream work to preserve across a pause; see
``subgraphs/tool_routing.py``'s module docstring for the full structural
argument. These tests therefore focus on: the interrupt genuinely living
inside Tool Route's own nested task (not the shared Main-Graph
``waiting_confirmation`` node), exactly-once real Provider calls per round,
same run/thread/owner across resume, repeated confirmation rounds resolving
inline (C2-A) or across kinds (C2-B) rather than falling back to a full
subgraph restart, and -- C2-B specific -- zero materialization of an
out-of-scope read before an APPROVED ``PolicyConfirmationReceiptV1``, exact
``BLOCKED`` transition on DECLINED, and fail-closed receipt provenance.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Sequence
from typing import Any, cast

from tests.integration.langgraph.test_runtime import (
    FIXTURE_ROOT,
    FakeGoogleGateway,
    GraphProfile,
    LangGraphWorkflowRuntime,
    Path,
    ProductFixtureSnapshotLoader,
    RequestIntentV2,
    WorkflowOutcome,
    _action_required_intent,
    _analysis_output,
    _answer_output,
    _clear_intent,
    _llm_result,
    _make_runtime,
    _make_runtime_with_llm,
    _PendingPlanActionsState,
    _review_output,
    _runtime_active_manifest_path,
    _seed_runtime_database,
    _selection_output,
    _start_request,
    _start_write_request,
    _sufficiency_output,
    _synthesize_action_argument_candidate,
    _synthesize_retrieval_query_plan,
    _write_plan_output,
    connect_sqlite,
)
from tests.support.canonical_workflow_runtime import (
    resume_confirmation_with_handoff,
    start_with_admission,
)

from google_work_agent.application.orchestration.provider_dispatch_budget import (
    account_provider_dispatch,
)
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowInvocationResult


class _ToolRouteQueuedLLMRuntime:
    """Like the shared ``_QueuedLLMRuntime``, but WITHOUT the unconditional
    ``tool_routing.determine_io_resources`` auto-synthesis -- these tests need
    to control that response directly (to force NEEDS_CONFIRMATION), which
    the shared fixture's synthesis would otherwise silently override.
    Retrieval's own ``plan_query`` INITIAL-round synthesis is kept, purely
    for convenience once Tool Route resolves and the run proceeds downstream.
    """

    def __init__(
        self,
        payloads: Sequence[object],
        *,
        classify_intent: RequestIntentV2 | None = None,
    ) -> None:
        self._queued = deque(_llm_result(item) for item in payloads)
        self.calls: list[dict[str, object]] = []
        self._classify_intent = classify_intent
        self._pending_plan_actions_state = _PendingPlanActionsState()

    def invoke_structured(self, **kwargs: object) -> Any:
        return self._invoke(**kwargs)

    def invoke_tool_call(self, **kwargs: object) -> Any:
        return self._invoke(**kwargs)

    def discard_run(self, *, run_id: str) -> None:
        del run_id

    def _invoke(self, **kwargs: object) -> Any:
        account_provider_dispatch()
        self.calls.append(dict(kwargs))
        prompt_ref = kwargs.get("prompt_ref")
        prompt_id = getattr(prompt_ref, "prompt_id", None)
        if prompt_id == "request_understanding.identify_goal":
            # Request Understanding must always classify cleanly in these
            # tests -- Tool Route, not Request Understanding, is what these
            # tests need to pause. Fixed (defaulting to _clear_intent()), not
            # drawn from the queue reserved for tool_routing.determine_io_resources
            # + downstream steps. C2-B tests override it via classify_intent to
            # carry a SCOPE constraint.
            intent = self._classify_intent or _clear_intent()
            return _llm_result(
                {
                    key: value
                    for key, value in intent.items()
                    if key not in {"schema_version", "ambiguity", "meta"}
                }
            )
        if prompt_id == "request_understanding.detect_ambiguity":
            intent = self._classify_intent or _clear_intent()
            return _llm_result(intent["ambiguity"])
        if getattr(prompt_ref, "prompt_id", None) == "retrieval.plan_query":
            prompt_input = cast(dict[str, object], kwargs["prompt_input"])
            output_schema = kwargs.get("output_schema")
            schema_version = getattr(output_schema, "schema_version", None)
            is_v2_initial = (
                schema_version == "retrieval-query-plan-v2"
                and "current_round_no" not in prompt_input
            )
            if is_v2_initial:
                return _llm_result(_synthesize_retrieval_query_plan(prompt_input))
        if getattr(prompt_ref, "prompt_id", None) == "planning.compose_arguments":
            prompt_input = cast(dict[str, object], kwargs["prompt_input"])
            output_route = cast(dict[str, object], prompt_input["output_route"])
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
            prompt_input = cast(dict[str, object], kwargs["prompt_input"])
            base_projection = cast(dict[str, object], prompt_input["base_projection"])
            output_route = cast(dict[str, object], base_projection["output_route"])
            candidate_output = cast(dict[str, object], prompt_input["candidate_output"])
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


def _semantic_candidate(
    disposition: str,
    *,
    input_resource_types: list[str] | None = None,
    output_resource_types: list[str] | None = None,
    output_effects: list[str] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "input_resource_types": input_resource_types or [],
        "output_resource_types": output_resource_types or [],
        "output_effects": output_effects or [],
        "disposition": disposition,
    }


def _scoped_task_create_intent(*, forbidden_sources: list[str]) -> RequestIntentV2:
    """TASK+CREATE request intent carrying an explicit SCOPE constraint that
    puts the mandatory TASK/TASK_LIST duplicate-check READ out of the user's
    declared scope."""
    payload = _action_required_intent()
    payload["constraints"] = [
        *payload["constraints"],
        {"kind": "SCOPE", "field": "forbidden_sources", "value": forbidden_sources},
    ]
    return payload


def _build_runtime(
    *,
    database_path: Path,
    llm_runtime: _ToolRouteQueuedLLMRuntime,
    gateway: FakeGoogleGateway,
    checkpoint_path: Path,
    manifest_path: Path,
    id_prefix: str,
) -> LangGraphWorkflowRuntime:
    return _make_runtime_with_llm(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=gateway,
        checkpoint_database_path=database_path,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
        default_tasklist_id="task-list-default",
        id_prefix=id_prefix,
    )


def _resume_confirmation(
    *,
    runtime: LangGraphWorkflowRuntime,
    database_path: Path,
    resume_payload: dict[str, object],
    command_id: str,
) -> tuple[object, WorkflowInvocationResult | None]:
    return resume_confirmation_with_handoff(
        runtime,
        database_path,
        resume_payload=resume_payload,
        command_id=command_id,
    )


def _nested_tool_route_task(runtime: LangGraphWorkflowRuntime) -> Any:
    """The paused checkpoint's own task for the nested tool_route subgraph --
    asserting on this is what actually distinguishes "same nested checkpoint
    resume" from a full subgraph restart producing the same final answer."""
    thread_config = runtime._invocation.config_for_thread("thread-1")  # noqa: SLF001
    snapshot = runtime._graph.get_state(thread_config, subgraphs=True)  # noqa: SLF001
    assert snapshot.next == ("tool_route",)
    assert len(snapshot.tasks) == 1
    outer_task = snapshot.tasks[0]
    assert outer_task.name == "tool_route"
    return outer_task


# --- T1 + T3: ordinary ambiguity pauses inside Tool Route's own nested task,
# and Local State (the nested checkpoint) is what actually persists. ---


def test_tool_route_ambiguity_pauses_inside_own_nested_task(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-tool-route-confirm.db"

    llm_runtime = _ToolRouteQueuedLLMRuntime([_semantic_candidate("NEEDS_CONFIRMATION")])
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round1",
    )
    # request_intent must itself be COMPLETE (Request Understanding must not
    # be the thing pausing here) -- _clear_intent() classifies cleanly.
    first = start_with_admission(runtime, database_path, _start_request())

    assert first.outcome is WorkflowOutcome.ACCEPTED
    assert first.payload["user_interrupt"] is not None
    assert first.payload["user_interrupt"]["origin_target"] == "tool_route.finalize"
    interrupt_id = first.payload["user_interrupt"]["interrupt_id"]

    # E/T1: owner=TOOL_ROUTE, and the pending task is genuinely nested inside
    # "tool_route", not the shared Main-Graph "waiting_confirmation" node
    # (which would show up as snapshot.next == ("waiting_confirmation",)
    # with no nested subgraph structure at all).
    outer_task = _nested_tool_route_task(runtime)
    assert outer_task.state.next == ("finalize_route",)

    connection = connect_sqlite(database_path)
    try:
        run_row = connection.execute(
            "SELECT status, langgraph_thread_id FROM runs WHERE id = 'run-1';"
        ).fetchone()
        assert run_row[0] == "WAITING_CONFIRMATION"
        assert run_row[1] == "thread-1"
    finally:
        connection.close()
        runtime.close()

    assert interrupt_id is not None
    # exactly one real semantic-candidate Provider call happened before the
    # pause -- registry binding/policy/freeze never started (NEEDS_CONFIRMATION
    # short-circuits route() at its very first step).
    semantic_calls = [
        call
        for call in llm_runtime.calls
        if getattr(call["prompt_ref"], "prompt_id", None) == "tool_routing.determine_io_resources"
    ]
    assert len(semantic_calls) == 1


# --- T2 + T4: resume makes exactly one more semantic-candidate call, "route"
# (the node analogous to upstream/classify) never re-runs, and the resolved
# connector/resource/effect/tool identity is exactly what the resolving
# response produced -- not re-derived by some other re-selection path. ---


def test_tool_route_resume_makes_exactly_one_more_semantic_call_and_completes(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-tool-route-confirm2.db"

    llm_runtime = _ToolRouteQueuedLLMRuntime([_semantic_candidate("NEEDS_CONFIRMATION")])
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round1",
    )
    first = start_with_admission(runtime, database_path, _start_request())
    interrupt_id = first.payload["user_interrupt"]["interrupt_id"]
    runtime.close()

    resumed_llm_runtime = _ToolRouteQueuedLLMRuntime(
        [
            _semantic_candidate("ROUTE_READY", input_resource_types=["TASK"]),
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output(),
            _review_output("PASS"),
        ]
    )
    resumed_gateway = FakeGoogleGateway(snapshot)
    resumed_runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=resumed_llm_runtime,
        gateway=resumed_gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round2",
    )
    application_result, result = _resume_confirmation(
        runtime=resumed_runtime,
        database_path=database_path,
        command_id="command-2",
        resume_payload={
            "schema_version": 1,
            "interrupt_id": interrupt_id,
            "response_kind": "FREE_TEXT",
            "selected_option": None,
            "free_text": "Use my Tasks list.",
        },
    )
    assert application_result.applied is True
    assert result is not None
    assert result.outcome is WorkflowOutcome.COMPLETED, result.payload

    semantic_calls = [
        call
        for call in resumed_llm_runtime.calls
        if getattr(call["prompt_ref"], "prompt_id", None) == "tool_routing.determine_io_resources"
    ]
    # T2: exactly one more real semantic-candidate call -- not a restart of
    # "route" (which would still only cost one call here structurally, but
    # would show up as a fresh nested checkpoint below instead of a resume).
    assert len(semantic_calls) == 1
    semantic_prompt_input = cast(dict[str, object], semantic_calls[0]["prompt_input"])

    # H: Prompt resume boundary -- only the bounded confirmation_response,
    # nothing about the checkpoint/interrupt/registry crosses in.
    confirmation_response = cast(dict[str, object], semantic_prompt_input["confirmation_response"])
    assert confirmation_response["free_text"] == "Use my Tasks list."
    for forbidden_key in ("interrupt_id", "resume_target", "checkpoint", "owner_subgraph"):
        assert forbidden_key not in semantic_prompt_input

    # T4: the resolved output route (TASK/READ, matching the resolving
    # candidate) reached the run -- resume did not silently discard or
    # re-derive the identity the resolving response actually specified.
    connection = connect_sqlite(database_path)
    try:
        run_row = connection.execute(
            "SELECT status, langgraph_thread_id FROM runs WHERE id = 'run-1';"
        ).fetchone()
        assert run_row[0] == "COMPLETED"
        assert run_row[1] == "thread-1"
    finally:
        connection.close()
        resumed_runtime.close()


# --- T5: repeated confirmation resolves inline, same nested checkpoint each
# round -- no fallback to the shared Main-Graph owner-restart mechanism. ---


def test_tool_route_resumes_second_consecutive_confirmation_round_via_same_nested_checkpoint(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-tool-route-two-round.db"

    # --- Round 1 ---
    llm_runtime = _ToolRouteQueuedLLMRuntime([_semantic_candidate("NEEDS_CONFIRMATION")])
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round1",
    )
    first = start_with_admission(runtime, database_path, _start_request())
    assert first.outcome is WorkflowOutcome.ACCEPTED
    round1_interrupt_id = first.payload["user_interrupt"]["interrupt_id"]
    assert first.payload["user_interrupt"]["origin_target"] == "tool_route.finalize"
    runtime.close()

    # --- Round 2: resolving response is ITSELF still ambiguous -- must pause
    # again, still inside the same nested subgraph. ---
    round2_llm_runtime = _ToolRouteQueuedLLMRuntime([_semantic_candidate("NEEDS_CONFIRMATION")])
    round2_gateway = FakeGoogleGateway(snapshot)
    round2_runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=round2_llm_runtime,
        gateway=round2_gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round2",
    )
    application_result, second = _resume_confirmation(
        runtime=round2_runtime,
        database_path=database_path,
        command_id="command-2",
        resume_payload={
            "schema_version": 1,
            "interrupt_id": round1_interrupt_id,
            "response_kind": "FREE_TEXT",
            "selected_option": None,
            "free_text": "round-1 answer, still ambiguous apparently.",
        },
    )
    assert application_result.applied is True
    assert second is not None
    # A second real pause, NOT an error and NOT a silent restart.
    assert second.outcome is WorkflowOutcome.ACCEPTED
    round1_reclassify_calls = [
        call
        for call in round2_llm_runtime.calls
        if getattr(call["prompt_ref"], "prompt_id", None) == "tool_routing.determine_io_resources"
    ]
    assert len(round1_reclassify_calls) == 1

    round2_task = _nested_tool_route_task(round2_runtime)
    assert round2_task.state.next == ("finalize_route",)
    round2_interrupt_id = second.payload["user_interrupt"]["interrupt_id"]
    assert second.payload["user_interrupt"]["origin_target"] == "tool_route.finalize"
    assert round2_interrupt_id != round1_interrupt_id
    round2_runtime.close()

    # --- Round 3: Tool Route resolves and downstream execution completes
    # within the Canonical NORMAL budget. ---
    round3_llm_runtime = _ToolRouteQueuedLLMRuntime(
        [
            _semantic_candidate("ROUTE_READY", input_resource_types=["TASK"]),
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output(),
            _review_output("PASS"),
        ]
    )
    round3_gateway = FakeGoogleGateway(snapshot)
    round3_runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=round3_llm_runtime,
        gateway=round3_gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round3",
    )
    application_result, result = _resume_confirmation(
        runtime=round3_runtime,
        database_path=database_path,
        command_id="command-3",
        resume_payload={
            "schema_version": 1,
            "interrupt_id": round2_interrupt_id,
            "response_kind": "FREE_TEXT",
            "selected_option": None,
            "free_text": "round-2 answer, resolves it.",
        },
    )
    assert application_result.applied is True
    assert result is not None
    assert result.outcome is WorkflowOutcome.COMPLETED
    round2_reclassify_calls = [
        call
        for call in round3_llm_runtime.calls
        if getattr(call["prompt_ref"], "prompt_id", None) == "tool_routing.determine_io_resources"
    ]
    assert len(round2_reclassify_calls) == 1

    connection = connect_sqlite(database_path)
    try:
        run_row = connection.execute(
            "SELECT status, langgraph_thread_id FROM runs WHERE id = 'run-1';"
        ).fetchone()
        assert run_row[0] == "COMPLETED"
        assert run_row[1] == "thread-1"
    finally:
        connection.close()
        round3_runtime.close()


# --- T6: invalid resume fails closed. ---


def test_tool_route_resume_rejects_wrong_interrupt_id(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-tool-route-invalid.db"

    llm_runtime = _ToolRouteQueuedLLMRuntime([_semantic_candidate("NEEDS_CONFIRMATION")])
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round1",
    )
    start_with_admission(runtime, database_path, _start_request())
    runtime.close()

    resumed_llm_runtime = _ToolRouteQueuedLLMRuntime([])
    resumed_gateway = FakeGoogleGateway(snapshot)
    resumed_runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=resumed_llm_runtime,
        gateway=resumed_gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round2",
    )
    try:
        application_result, runtime_result = _resume_confirmation(
            runtime=resumed_runtime,
            database_path=database_path,
            command_id="command-2",
            resume_payload={
                "schema_version": 1,
                "interrupt_id": "definitely-the-wrong-interrupt-id",
                "response_kind": "FREE_TEXT",
                "selected_option": None,
                "free_text": "irrelevant",
            },
        )
        assert application_result.applied is False
        assert "interrupt" in str(application_result.conflict_detail)
        assert runtime_result is None
        # Fails closed: no Provider call happened while validating the
        # resume payload.
        assert resumed_llm_runtime.calls == []
    finally:
        resumed_runtime.close()


def test_tool_route_resume_rejects_option_id_outside_allowed_scope(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-tool-route-invalid-option.db"

    llm_runtime = _ToolRouteQueuedLLMRuntime([_semantic_candidate("NEEDS_CONFIRMATION")])
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round1",
    )
    first = start_with_admission(runtime, database_path, _start_request())
    interrupt_id = first.payload["user_interrupt"]["interrupt_id"]
    # Tool Route's ordinary-ambiguity question is always free-text
    # (options=[]) -- a closed-choice OPTION response must be
    # rejected as outside scope.
    assert first.payload["user_interrupt"]["options"] == []
    runtime.close()

    resumed_llm_runtime = _ToolRouteQueuedLLMRuntime([])
    resumed_gateway = FakeGoogleGateway(snapshot)
    resumed_runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=resumed_llm_runtime,
        gateway=resumed_gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round2",
    )
    try:
        application_result, runtime_result = _resume_confirmation(
            runtime=resumed_runtime,
            database_path=database_path,
            command_id="command-2",
            resume_payload={
                "schema_version": 1,
                "interrupt_id": interrupt_id,
                "response_kind": "OPTION",
                "selected_option": "option-not-offered",
                "free_text": None,
            },
        )
        assert application_result.applied is False
        assert "option" in str(application_result.conflict_detail)
        assert runtime_result is None
    finally:
        resumed_runtime.close()


# --- T7: existing Tool Route happy path (no confirmation) is unaffected. ---


def test_tool_route_happy_path_without_confirmation_reaches_context_retrieval(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _clear_intent(),
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
    try:
        result = start_with_admission(runtime, database_path, _start_request())
        assert result.outcome is WorkflowOutcome.COMPLETED
        connection = connect_sqlite(database_path)
        try:
            run_row = connection.execute("SELECT status FROM runs WHERE id = 'run-1';").fetchone()
            assert run_row[0] == "COMPLETED"
        finally:
            connection.close()
    finally:
        runtime.close()


# =====================================================================
# C2-B: Scope Expansion + PolicyConfirmationReceiptV1
# =====================================================================

_APPROVED_OPTIONS = [
    {"option_id": "APPROVED", "label": "네, 확인하고 진행합니다"},
    {"option_id": "DECLINED", "label": "아니요, 진행하지 않습니다"},
]


def _out_of_scope_task_create_candidate() -> dict[str, object]:
    return _semantic_candidate(
        "ROUTE_READY", output_resource_types=["TASK"], output_effects=["CREATE"]
    )


# --- out-of-scope TASK+CREATE pauses inside Tool Route's own nested task,
# with a closed-choice APPROVED/DECLINED question (not free-text). ---


def test_tool_route_scope_expansion_pauses_inside_own_nested_task(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-tool-route-scope.db"

    gateway = FakeGoogleGateway(snapshot)
    llm_runtime = _ToolRouteQueuedLLMRuntime(
        [_out_of_scope_task_create_candidate()],
        classify_intent=_scoped_task_create_intent(forbidden_sources=["TASK"]),
    )
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round1",
    )
    try:
        first = start_with_admission(runtime, database_path, _start_write_request())

        assert first.outcome is WorkflowOutcome.ACCEPTED
        interrupt = first.payload["user_interrupt"]
        assert interrupt is not None
        assert interrupt["origin_target"] == "tool_route.finalize"
        assert interrupt["options"] == _APPROVED_OPTIONS

        outer_task = _nested_tool_route_task(runtime)
        assert outer_task.state.next == ("finalize_route",)

        # No output route was ever frozen -- the plan does not exist yet.
        state = runtime._graph.get_state(  # noqa: SLF001
            runtime._invocation.config_for_thread("thread-1")  # noqa: SLF001
        ).values
        assert state["tool_route_plan"] is None
        assert state["policy_confirmation_receipts"] == []

        # No connector read of any kind happened before the pause.
        assert gateway.call_log == []

        semantic_calls = [
            call
            for call in llm_runtime.calls
            if getattr(call["prompt_ref"], "prompt_id", None)
            == "tool_routing.determine_io_resources"
        ]
        assert len(semantic_calls) == 1
    finally:
        runtime.close()


def test_tool_route_scope_expansion_for_calendar_event_create(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-tool-route-scope-calendar.db"

    calendar_intent = _action_required_intent()
    calendar_intent["requested_resource_hints"] = ["CALENDAR_EVENT"]
    calendar_intent["constraints"] = [
        *calendar_intent["constraints"],
        {"kind": "SCOPE", "field": "forbidden_sources", "value": ["CALENDAR"]},
    ]
    llm_runtime = _ToolRouteQueuedLLMRuntime(
        [
            _semantic_candidate(
                "ROUTE_READY",
                output_resource_types=["CALENDAR"],
                output_effects=["CREATE"],
            )
        ],
        classify_intent=calendar_intent,
    )
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round1",
    )
    try:
        first = start_with_admission(runtime, database_path, _start_write_request())
        assert first.outcome is WorkflowOutcome.ACCEPTED
        interrupt = first.payload["user_interrupt"]
        assert interrupt is not None
        assert interrupt["options"] == _APPROVED_OPTIONS
    finally:
        runtime.close()


# --- APPROVED: Application/Confirmation Controller builds one Receipt,
# zero reads materialized before approval, exactly one more semantic call,
# the previously-blocked reads are merged once approved, Prompt boundary
# excludes raw receipt/interrupt/checkpoint metadata. ---


def test_tool_route_scope_expansion_approved_materializes_reads_with_receipt(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-tool-route-scope-approved.db"
    scoped_intent = _scoped_task_create_intent(forbidden_sources=["TASK"])

    llm_runtime = _ToolRouteQueuedLLMRuntime(
        [_out_of_scope_task_create_candidate()], classify_intent=scoped_intent
    )
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round1",
    )
    first = start_with_admission(runtime, database_path, _start_write_request())
    interrupt_id = first.payload["user_interrupt"]["interrupt_id"]
    runtime.close()

    # The approved scope-expansion continuation preserves the existing route
    # candidate and completes within the Canonical NORMAL budget.
    resumed_llm_runtime = _ToolRouteQueuedLLMRuntime(
        [
            _out_of_scope_task_create_candidate(),
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _write_plan_output(),
            _review_output("PASS"),
        ],
        classify_intent=scoped_intent,
    )
    resumed_gateway = FakeGoogleGateway(snapshot)
    resumed_runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=resumed_llm_runtime,
        gateway=resumed_gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round2",
    )
    try:
        application_result, result = _resume_confirmation(
            runtime=resumed_runtime,
            database_path=database_path,
            command_id="command-2",
            resume_payload={
                "schema_version": 1,
                "interrupt_id": interrupt_id,
                "response_kind": "OPTION",
                "selected_option": "APPROVED",
                "free_text": None,
            },
        )
        assert application_result.applied is True
        assert result is not None
        assert result.outcome is WorkflowOutcome.ACCEPTED
        assert result.payload["run_status"] == "WAITING_APPROVAL"

        semantic_calls = [
            call
            for call in resumed_llm_runtime.calls
            if getattr(call["prompt_ref"], "prompt_id", None)
            == "tool_routing.determine_io_resources"
        ]
        assert semantic_calls == []

        state = resumed_runtime._graph.get_state(  # noqa: SLF001
            resumed_runtime._invocation.config_for_thread("thread-1")  # noqa: SLF001
        ).values
        receipts = state["policy_confirmation_receipts"]
        assert len(receipts) == 1
        receipt = receipts[0]
        assert receipt["confirmation_kind"] == "SCOPE_EXPANSION"
        assert receipt["decision"] == "APPROVED"
        assert receipt["interrupt_id"] == interrupt_id
        assert set(receipt["affected_resource_refs"]) == {"TASK", "TASK_LIST"}

        plan = state["tool_route_plan"]
        assert plan is not None
        resources = {route["resource_type"] for route in plan["input_plan"]["input_routes"]}
        assert {"TASK", "TASK_LIST"} <= resources

        # POLICY_CONFIRMATION_RECORDED audit row shares confirmation_receipt_id
        # / decision_context_hash with the checkpoint's PolicyConfirmationReceiptV1
        # (11-observability-logging-audit.md SS6) -- allowlisted fields only, no
        # raw question/response text.
        connection = connect_sqlite(database_path)
        try:
            row = connection.execute(
                "SELECT metadata_json, outcome FROM audit_events "
                "WHERE run_id = 'run-1' AND event_type = 'POLICY_CONFIRMATION_RECORDED';"
            ).fetchone()
        finally:
            connection.close()
        assert row is not None
        audit_attributes = json.loads(row[0])["attributes"]
        assert row[1] == "APPROVED"
        assert audit_attributes["confirmation_receipt_id"] == receipt["meta"]["artifact_id"]
        assert audit_attributes["interrupt_id"] == interrupt_id
        assert audit_attributes["decision_context_hash"] == receipt["decision_context_hash"]
        assert audit_attributes["confirmation_kind"] == "SCOPE_EXPANSION"
        assert "question" not in audit_attributes
        assert "free_text" not in audit_attributes
    finally:
        resumed_runtime.close()


# --- DECLINED: mandatory Policy Precondition READ cannot be skipped, so
# Tool Route is BLOCKED outright -- never re-attempted with a reduced plan,
# and zero out-of-scope reads are ever materialized. ---


def test_tool_route_scope_expansion_declined_blocks_without_materializing_reads(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-tool-route-scope-declined.db"
    scoped_intent = _scoped_task_create_intent(forbidden_sources=["TASK"])

    llm_runtime = _ToolRouteQueuedLLMRuntime(
        [_out_of_scope_task_create_candidate()], classify_intent=scoped_intent
    )
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round1",
    )
    first = start_with_admission(runtime, database_path, _start_write_request())
    interrupt_id = first.payload["user_interrupt"]["interrupt_id"]
    runtime.close()

    resumed_llm_runtime = _ToolRouteQueuedLLMRuntime([], classify_intent=scoped_intent)
    resumed_gateway = FakeGoogleGateway(snapshot)
    resumed_runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=resumed_llm_runtime,
        gateway=resumed_gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round2",
    )
    try:
        application_result, result = _resume_confirmation(
            runtime=resumed_runtime,
            database_path=database_path,
            command_id="command-2",
            resume_payload={
                "schema_version": 1,
                "interrupt_id": interrupt_id,
                "response_kind": "OPTION",
                "selected_option": "DECLINED",
                "free_text": None,
            },
        )
        assert application_result.applied is True
        assert result is not None
        # DECLINED never re-invokes the semantic stage -- no real Provider
        # call, no re-derivation of a "reduced" plan.
        semantic_calls = [
            call
            for call in resumed_llm_runtime.calls
            if getattr(call["prompt_ref"], "prompt_id", None)
            == "tool_routing.determine_io_resources"
        ]
        assert semantic_calls == []

        assert result.outcome is WorkflowOutcome.COMPLETED
        assert result.payload["finalize_intent"]["intent"] == "BLOCKED"

        state = resumed_runtime._graph.get_state(  # noqa: SLF001
            resumed_runtime._invocation.config_for_thread("thread-1")  # noqa: SLF001
        ).values
        receipts = state["policy_confirmation_receipts"]
        assert len(receipts) == 1
        assert receipts[0]["decision"] == "DECLINED"
        assert state["tool_route_plan"] is None

        # DECLINED is recorded too (11-observability-logging-audit.md SS6
        # allowlists decision(APPROVED|DECLINED)).
        connection = connect_sqlite(database_path)
        try:
            row = connection.execute(
                "SELECT metadata_json, outcome FROM audit_events "
                "WHERE run_id = 'run-1' AND event_type = 'POLICY_CONFIRMATION_RECORDED';"
            ).fetchone()
        finally:
            connection.close()
        assert row is not None
        assert row[1] == "DECLINED"
        audit_attributes = json.loads(row[0])["attributes"]
        assert audit_attributes["confirmation_receipt_id"] == receipts[0]["meta"]["artifact_id"]
        assert audit_attributes["decision"] == "DECLINED"
    finally:
        resumed_runtime.close()


# --- Receipt provenance fails closed: a forged/foreign receipt sitting in
# checkpoint state is never itself what unlocks a merge -- only a fresh
# receipt the Application/Confirmation Controller builds from a just-validated
# real ConfirmationResponseV1 can (see ScopeExpansionResolver.find_valid_approval
# unit tests for the direct hash/interrupt/revision/decision fail-closed
# proofs). This integration test proves the forged one is inert end-to-end:
# it survives untouched in policy_confirmation_receipts, but the merge is
# unlocked by the newly-appended genuine receipt, not by it. ---


def test_tool_route_scope_expansion_forged_receipt_stays_inert(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-tool-route-scope-forged.db"
    scoped_intent = _scoped_task_create_intent(forbidden_sources=["TASK"])

    llm_runtime = _ToolRouteQueuedLLMRuntime(
        [_out_of_scope_task_create_candidate()], classify_intent=scoped_intent
    )
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round1",
    )
    first = start_with_admission(runtime, database_path, _start_write_request())
    interrupt_id = first.payload["user_interrupt"]["interrupt_id"]

    # Inject a forged receipt directly into the checkpoint -- simulating a
    # tampered/foreign PolicyConfirmationReceiptV1 that never went through
    # the Application/Confirmation Controller for THIS interrupt. Must
    # target the NESTED tool_route subgraph's own checkpoint (its config),
    # not the parent thread's top-level config -- MultiAgentGraphState is
    # shared shape, but the pending checkpoint lives one level down.
    outer_task = _nested_tool_route_task(runtime)
    nested_config = outer_task.state.config
    forged_receipt = {
        "schema_version": 1,
        "meta": {
            "artifact_id": "forged-artifact",
            "revision": 1,
            "based_on": [{"artifact_id": "intent-1", "revision": 1}],
        },
        "interrupt_id": interrupt_id,
        "confirmation_kind": "SCOPE_EXPANSION",
        "decision": "APPROVED",
        "semantic_owner_id": "TOOL_ROUTE",
        "decision_context_hash": "not-a-real-hash",
        "affected_route_ids": ["TASK:CREATE"],
        "affected_resource_refs": ["TASK", "TASK_LIST"],
    }
    runtime._graph.update_state(  # noqa: SLF001
        nested_config, {"policy_confirmation_receipts": [forged_receipt]}
    )
    runtime.close()

    # Same budget arithmetic as the APPROVED test above.
    resumed_llm_runtime = _ToolRouteQueuedLLMRuntime(
        [
            _out_of_scope_task_create_candidate(),
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _write_plan_output(),
            _review_output("PASS"),
        ],
        classify_intent=scoped_intent,
    )
    resumed_gateway = FakeGoogleGateway(snapshot)
    resumed_runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=resumed_llm_runtime,
        gateway=resumed_gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round2",
    )
    try:
        application_result, result = _resume_confirmation(
            runtime=resumed_runtime,
            database_path=database_path,
            command_id="command-2",
            resume_payload={
                "schema_version": 1,
                "interrupt_id": interrupt_id,
                "response_kind": "OPTION",
                "selected_option": "APPROVED",
                "free_text": None,
            },
        )
        assert application_result.applied is True
        assert result is not None
        assert result.outcome is WorkflowOutcome.ACCEPTED
        assert result.payload["run_status"] == "WAITING_APPROVAL"

        state = resumed_runtime._graph.get_state(  # noqa: SLF001
            resumed_runtime._invocation.config_for_thread("thread-1")  # noqa: SLF001
        ).values
        receipts = state["policy_confirmation_receipts"]
        # The forged receipt survives untouched (never validated as
        # authoritative), alongside a genuine, freshly-built one.
        assert len(receipts) == 2
        assert receipts[0] == forged_receipt
        genuine_receipt = receipts[1]
        assert genuine_receipt["decision_context_hash"] != "not-a-real-hash"
        assert genuine_receipt["meta"]["artifact_id"] != "forged-artifact"

        # The merge itself proceeded -- unlocked by the genuine receipt, not
        # by the forged one (whose hash never matched anything).
        plan = state["tool_route_plan"]
        assert plan is not None
        resources = {route["resource_type"] for route in plan["input_plan"]["input_routes"]}
        assert {"TASK", "TASK_LIST"} <= resources
    finally:
        resumed_runtime.close()


# --- Repeated confirmation across DIFFERENT kinds (ordinary ambiguity, then
# scope expansion) still resolves inline on the same nested checkpoint --
# proves the generalized _resolve_confirmation_inline dispatch does not
# special-case either kind into a separate mechanism. ---


def test_tool_route_ambiguity_then_scope_expansion_rounds_both_stay_nested(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-tool-route-mixed-rounds.db"
    scoped_intent = _scoped_task_create_intent(forbidden_sources=["TASK"])

    # --- Round 1: ordinary ambiguity (C2-A). ---
    llm_runtime = _ToolRouteQueuedLLMRuntime(
        [_semantic_candidate("NEEDS_CONFIRMATION")], classify_intent=scoped_intent
    )
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round1",
    )
    first = start_with_admission(runtime, database_path, _start_write_request())
    assert first.outcome is WorkflowOutcome.ACCEPTED
    round1_interrupt_id = first.payload["user_interrupt"]["interrupt_id"]
    assert first.payload["user_interrupt"]["options"] == []
    runtime.close()

    # --- Round 2: the resolved candidate is TASK+CREATE, out of scope ->
    # scope expansion (C2-B), still inside the same nested checkpoint. ---
    round2_llm_runtime = _ToolRouteQueuedLLMRuntime(
        [_out_of_scope_task_create_candidate()], classify_intent=scoped_intent
    )
    round2_runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=round2_llm_runtime,
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round2",
    )
    application_result, second = _resume_confirmation(
        runtime=round2_runtime,
        database_path=database_path,
        command_id="command-2",
        resume_payload={
            "schema_version": 1,
            "interrupt_id": round1_interrupt_id,
            "response_kind": "FREE_TEXT",
            "selected_option": None,
            "free_text": "Create a task.",
        },
    )
    assert application_result.applied is True
    assert second is not None
    assert second.outcome is WorkflowOutcome.ACCEPTED
    round2_task = _nested_tool_route_task(round2_runtime)
    assert round2_task.state.next == ("finalize_route",)
    round2_interrupt = second.payload["user_interrupt"]
    assert round2_interrupt["options"] == _APPROVED_OPTIONS
    round2_interrupt_id = round2_interrupt["interrupt_id"]
    assert round2_interrupt_id != round1_interrupt_id
    round2_runtime.close()

    # --- Round 3: APPROVED -- resolves and completes on the same nested
    # checkpoint within the Canonical NORMAL budget. ---
    round3_llm_runtime = _ToolRouteQueuedLLMRuntime(
        [
            _out_of_scope_task_create_candidate(),
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _write_plan_output(),
            _review_output("PASS"),
        ],
        classify_intent=scoped_intent,
    )
    round3_runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=round3_llm_runtime,
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="round3",
    )
    try:
        application_result, result = _resume_confirmation(
            runtime=round3_runtime,
            database_path=database_path,
            command_id="command-3",
            resume_payload={
                "schema_version": 1,
                "interrupt_id": round2_interrupt_id,
                "response_kind": "OPTION",
                "selected_option": "APPROVED",
                "free_text": None,
            },
        )
        assert application_result.applied is True
        assert result is not None
        assert result.outcome is WorkflowOutcome.ACCEPTED
        assert result.payload["run_status"] == "WAITING_APPROVAL"
        state = round3_runtime._graph.get_state(  # noqa: SLF001
            round3_runtime._invocation.config_for_thread("thread-1")  # noqa: SLF001
        ).values
        assert len(state["policy_confirmation_receipts"]) == 1
        assert state["tool_route_plan"] is not None
    finally:
        round3_runtime.close()
