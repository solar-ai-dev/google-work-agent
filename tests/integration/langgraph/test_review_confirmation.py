"""C6: Review Confirmation -- nested subgraph checkpoint resume integration
tests.

Review's only CONFIRM trigger is ``review.inspect``
(``PlanReviewAgent.invoke_inspect_llm_from_evidence``) returning
``status="CONFIRM"`` -- ``review.recheck``'s tool set (``review_pass``/
``review_block`` only) makes CONFIRM structurally unreachable from
``mode="recheck"``. Review is the deepest owner in the SIX_ROLE_BASELINE
chain (Request Understanding -> Tool Route -> Retrieval -> Work Analysis ->
Planning -> Review all consume at least one real LLM call each), so
Review's own first call already lands on NORMAL_MAX_LLM_CALLS (8) -- there
is no room left for a second (resolving) call under the NORMAL budget
profile. Tests that need the resolve round to actually execute bump
``retry_budget.profile`` to ``RETRIEVAL_HEAVY`` (cap 14) via
``runtime._graph.update_state(...)`` on the paused nested checkpoint --
exactly the same state-injection technique C2-B's own tests already use for
forged receipts -- purely to get past this orthogonal budget ceiling; it
changes no production code and does not touch D1/P1/P7.

These tests focus on: the interrupt genuinely living inside Review's own
nested task (not the shared Main-Graph ``waiting_confirmation`` node), zero
re-execution of Tool Route/Retrieval/Work Analysis/Planning on resume,
exactly one more real ``review.inspect`` call per round, Review mode/local
state preservation, repeated confirmation rounds resolving inline, existing
PASS/REVISE/RETRIEVE_MORE/ROUTE_RECONSIDERATION/BLOCK edges unaffected, and
fail-closed invalid resume.
"""

from __future__ import annotations

from typing import Any

from tests.integration.langgraph.test_runtime import (
    FIXTURE_ROOT,
    FakeGoogleGateway,
    GraphProfile,
    LangGraphWorkflowRuntime,
    Path,
    ProductFixtureSnapshotLoader,
    WorkflowOutcome,
    _action_required_intent,
    _analysis_output,
    _answer_output,
    _clear_intent,
    _llm_result,
    _make_runtime,
    _make_runtime_with_llm,
    _QueuedLLMRuntime,
    _review_output,
    _runtime_active_manifest_path,
    _seed_runtime_database,
    _selection_output,
    _start_request,
    _start_write_request,
    _sufficiency_output,
    _write_plan_output,
    connect_sqlite,
)
from tests.support.canonical_workflow_runtime import (
    resume_confirmation_with_handoff,
    start_with_admission,
)


def _confirmation() -> dict[str, object]:
    return {
        "reason_code": "REVIEW_TARGET_AMBIGUITY",
        "question": "Which recipient should the review treat as primary?",
    }


def _build_runtime(
    *,
    database_path: Path,
    llm_runtime: _QueuedLLMRuntime,
    gateway: FakeGoogleGateway,
    checkpoint_path: Path,
    manifest_path: Path,
    id_prefix: str,
) -> LangGraphWorkflowRuntime:
    runtime = _make_runtime_with_llm(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=gateway,
        checkpoint_database_path=database_path,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
        default_tasklist_id="task-list-default",
        id_prefix=id_prefix,
    )
    initial_state = runtime._invocation._initial_state  # noqa: SLF001

    def retrieval_heavy_initial_state(request: object) -> dict[str, object]:
        state = initial_state(request)  # type: ignore[arg-type]
        budget = dict(state["retry_budget"])
        budget["profile"] = "RETRIEVAL_HEAVY"
        state["retry_budget"] = budget  # type: ignore[typeddict-item]
        return state

    runtime._invocation._initial_state = retrieval_heavy_initial_state  # noqa: SLF001
    return runtime


def _queue_more(llm_runtime: _QueuedLLMRuntime, payloads: list[object]) -> None:
    """Feed more responses into an already-constructed ``_QueuedLLMRuntime``
    ahead of a ``.resume()`` call. Reuses the SAME runtime/llm instance
    across start->resume -- Review's ``resolve_evidence_projection`` depends
    on the run-memory-only ``RunScopedEvidenceStore`` (D1, out of C6's
    scope), same constraint already documented for Work Analysis/Planning
    in C4/C5."""
    llm_runtime._queued.extend(_llm_result(item) for item in payloads)  # noqa: SLF001


def _attempt_confirmation(
    *,
    runtime: LangGraphWorkflowRuntime,
    database_path: Path,
    resume_payload: dict[str, object],
    command_id: str,
) -> tuple[object, object | None]:
    return resume_confirmation_with_handoff(
        runtime,
        database_path,
        resume_payload=resume_payload,
        command_id=command_id,
    )


def _resume_confirmation(
    *,
    runtime: LangGraphWorkflowRuntime,
    database_path: Path,
    resume_payload: dict[str, object],
    command_id: str,
) -> object | None:
    application_result, runtime_result = _attempt_confirmation(
        runtime=runtime,
        database_path=database_path,
        resume_payload=resume_payload,
        command_id=command_id,
    )
    assert application_result.applied is True  # type: ignore[attr-defined]
    return runtime_result


def _nested_review_task(runtime: LangGraphWorkflowRuntime) -> Any:
    """The paused checkpoint's own task for the nested review subgraph --
    asserting on this is what actually distinguishes "same nested checkpoint
    resume" from a full subgraph restart."""
    thread_config = runtime._invocation.config_for_thread("thread-1")  # noqa: SLF001
    snapshot = runtime._graph.get_state(thread_config, subgraphs=True)  # noqa: SLF001
    assert snapshot.next == ("review",)
    assert len(snapshot.tasks) == 1
    outer_task = snapshot.tasks[0]
    assert outer_task.name == "review"
    return outer_task


def _grant_extra_budget(runtime: LangGraphWorkflowRuntime) -> None:
    """Assert that the test runtime entered with the heavy budget fixture."""
    outer_task = _nested_review_task(runtime)
    assert outer_task.state.values["retry_budget"]["profile"] == "RETRIEVAL_HEAVY"


def _review_calls(llm_runtime: _QueuedLLMRuntime, prompt_id: str) -> list[dict[str, object]]:
    return [
        call
        for call in llm_runtime.calls
        if getattr(call["prompt_ref"], "prompt_id", None) == prompt_id
    ]


def _upstream_calls(llm_runtime: _QueuedLLMRuntime) -> list[dict[str, object]]:
    return [
        call
        for call in llm_runtime.calls
        if str(getattr(call["prompt_ref"], "prompt_id", "")).startswith(
            ("retrieval.", "acquisition.", "tool_route.", "work_analysis.", "planning.")
        )
    ]


def _start_to_first_confirmation(
    *,
    database_path: Path,
    gateway: FakeGoogleGateway,
    checkpoint_path: Path,
    manifest_path: Path,
    llm_payloads: list[object],
) -> tuple[LangGraphWorkflowRuntime, _QueuedLLMRuntime, dict[str, Any]]:
    llm_runtime = _QueuedLLMRuntime(llm_payloads)
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        id_prefix="run",
    )
    first = start_with_admission(runtime, database_path, _start_write_request())
    assert first.outcome is WorkflowOutcome.ACCEPTED
    return runtime, llm_runtime, first.payload


_ANSWER_QUEUE_TO_REVIEW = [
    _clear_intent(),
    _selection_output(),
    _sufficiency_output("SUFFICIENT"),
    _analysis_output(),
    _answer_output(),
]

# canonical_response_runtime.canonicalize_answer_only_decision() routes a
# Planning ANSWER_ONLY result straight to Response Synthesis instead of
# Review (docs/design/06-agent-workflow.md: "Planning ANSWER_ONLY ->
# Response Synthesis"), so this module's actual purpose -- testing Review's
# own CONFIRM/BLOCK/resume mechanics -- needs a plan Review will actually
# see. Every test below that pauses/resumes/blocks *inside Review* uses
# this ACTION queue; only test_review_pass_answer_target_completes (which
# specifically covers the ANSWER-target PASS->Finalize happy path,
# unaffected by C6) still uses _ANSWER_QUEUE_TO_REVIEW above.
_ACTION_QUEUE_TO_REVIEW = [
    _action_required_intent(),
    _selection_output(),
    _sufficiency_output("SUFFICIENT"),
    _analysis_output(),
    _write_plan_output(),
]


# --- T1 + T2: CONFIRM pauses inside Review's own nested task, same
# run/thread/owner. ---


def test_review_confirm_pauses_inside_own_nested_task(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-review-confirm.db"

    gateway = FakeGoogleGateway(snapshot)
    runtime, llm_runtime, payload = _start_to_first_confirmation(
        database_path=database_path,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        llm_payloads=[
            *_ACTION_QUEUE_TO_REVIEW,
            _review_output("CONFIRM", confirmation=_confirmation()),
        ],
    )
    try:
        interrupt = payload["user_interrupt"]
        assert interrupt is not None
        assert interrupt["origin_target"] == "review.inspect"
        assert interrupt["interrupt_id"] is not None

        # T1: nested pending task is genuinely "review".
        outer_task = _nested_review_task(runtime)
        assert outer_task.state.next == ("finalize",)

        # T2: same run/thread, owner = REVIEW.
        connection = connect_sqlite(database_path)
        try:
            run_row = connection.execute(
                "SELECT status, langgraph_thread_id FROM runs WHERE id = 'run-1';"
            ).fetchone()
            assert run_row[0] == "WAITING_CONFIRMATION"
            assert run_row[1] == "thread-1"
        finally:
            connection.close()

        assert len(_review_calls(llm_runtime, "review.inspect")) == 1
    finally:
        runtime.close()


# --- T3 + T4: resume re-executes no upstream owner; Review invocation_id
# proves init/review never replayed. ---


def test_review_resume_does_not_re_execute_upstream(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-review-resume.db"

    gateway = FakeGoogleGateway(snapshot)
    runtime, llm_runtime, payload = _start_to_first_confirmation(
        database_path=database_path,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        llm_payloads=[
            *_ACTION_QUEUE_TO_REVIEW,
            _review_output("CONFIRM", confirmation=_confirmation()),
        ],
    )
    interrupt_id = payload["user_interrupt"]["interrupt_id"]
    reads_before_resume = len(gateway.call_log)

    state_before = runtime._graph.get_state(  # noqa: SLF001
        runtime._invocation.config_for_thread("thread-1"),
        subgraphs=True,  # noqa: SLF001
    )
    invocation_id_before = state_before.tasks[0].state.values["__review_agent_local__"][
        "invocation_id"
    ]
    calls_before_resume = len(llm_runtime.calls)
    _grant_extra_budget(runtime)

    try:
        _queue_more(llm_runtime, [_review_output("PASS")])
        second = _resume_confirmation(
            runtime=runtime,
            database_path=database_path,
            resume_payload={
                "schema_version": 1,
                "interrupt_id": interrupt_id,
                "response_kind": "FREE_TEXT",
                "selected_option": None,
                "free_text": "Use the primary recipient.",
            },
            command_id="command-2",
        )
        assert second is not None
        # ACTION plan + PASS stops at WAITING_APPROVAL, not COMPLETED --
        # Review having run and rendered a real PASS decision (not full
        # write execution) is what this test proves.
        assert second.outcome is WorkflowOutcome.ACCEPTED

        # T4: zero provider reads happened on resume.
        assert len(gateway.call_log) == reads_before_resume
        calls_during_resume = llm_runtime.calls[calls_before_resume:]
        assert _upstream_calls(llm_runtime) == _upstream_calls(llm_runtime)[:calls_before_resume]
        resume_prompt_ids = [
            getattr(call["prompt_ref"], "prompt_id", None) for call in calls_during_resume
        ]
        assert resume_prompt_ids == ["review.inspect"]

        # T3: invocation_id unchanged -- "init"/"review" never replayed.
        state = runtime._graph.get_state(  # noqa: SLF001
            runtime._invocation.config_for_thread("thread-1")  # noqa: SLF001
        ).values
        node_log = state["trace_context"]["agent_node_log"]
        review_entries = [entry for entry in node_log if entry["agent_subgraph_id"] == "review"]
        init_entries = [entry for entry in review_entries if entry["node_name"] == "init"]
        assert len(init_entries) == 1
        assert init_entries[0]["agent_invocation_id"] == invocation_id_before
        assert all(entry["agent_invocation_id"] == invocation_id_before for entry in review_entries)
    finally:
        runtime.close()


# --- T5: confirmation_response reaches review.inspect's prompt_input, and
# Prompt boundary excludes checkpoint/interrupt metadata. ---


def test_review_resume_applies_confirmation_response_within_prompt_boundary(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-review-prompt-boundary.db"

    gateway = FakeGoogleGateway(snapshot)
    runtime, llm_runtime, payload = _start_to_first_confirmation(
        database_path=database_path,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        llm_payloads=[
            *_ACTION_QUEUE_TO_REVIEW,
            _review_output("CONFIRM", confirmation=_confirmation()),
        ],
    )
    interrupt_id = payload["user_interrupt"]["interrupt_id"]
    calls_before_resume = len(llm_runtime.calls)
    _grant_extra_budget(runtime)

    try:
        _queue_more(llm_runtime, [_review_output("PASS")])
        result = _resume_confirmation(
            runtime=runtime,
            database_path=database_path,
            resume_payload={
                "schema_version": 1,
                "interrupt_id": interrupt_id,
                "response_kind": "FREE_TEXT",
                "selected_option": None,
                "free_text": "Use the primary recipient.",
            },
            command_id="command-2",
        )
        assert result is not None

        calls_during_resume = llm_runtime.calls[calls_before_resume:]
        inspect_calls = [
            call
            for call in calls_during_resume
            if getattr(call["prompt_ref"], "prompt_id", None) == "review.inspect"
        ]
        assert len(inspect_calls) == 1
        prompt_input = inspect_calls[0]["prompt_input"]
        assert isinstance(prompt_input, dict)
        confirmation_response = prompt_input["confirmation_response"]
        assert isinstance(confirmation_response, dict)
        assert confirmation_response["free_text"] == "Use the primary recipient."

        for forbidden_key in (
            "interrupt_id",
            "resume_target",
            "checkpoint",
            "owner_subgraph",
            "policy_confirmation_receipts",
        ):
            assert forbidden_key not in prompt_input
    finally:
        runtime.close()


# --- T6: repeated confirmation resolves inline, same nested checkpoint each
# round. ---


def test_review_resumes_second_consecutive_confirmation_round_via_same_nested_checkpoint(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-review-two-round.db"

    gateway = FakeGoogleGateway(snapshot)
    runtime, llm_runtime, payload = _start_to_first_confirmation(
        database_path=database_path,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        llm_payloads=[
            *_ACTION_QUEUE_TO_REVIEW,
            _review_output("CONFIRM", confirmation=_confirmation()),
        ],
    )
    round1_interrupt_id = payload["user_interrupt"]["interrupt_id"]
    upstream_before = _upstream_calls(llm_runtime)
    _grant_extra_budget(runtime)

    try:
        # --- Round 2: still ambiguous -- must pause again, still inside the
        # same nested subgraph. ---
        _queue_more(llm_runtime, [_review_output("CONFIRM", confirmation=_confirmation())])
        second = _resume_confirmation(
            runtime=runtime,
            database_path=database_path,
            resume_payload={
                "schema_version": 1,
                "interrupt_id": round1_interrupt_id,
                "response_kind": "FREE_TEXT",
                "selected_option": None,
                "free_text": "round-1 answer, still ambiguous apparently.",
            },
            command_id="command-2",
        )
        assert second is not None
        assert second.outcome is WorkflowOutcome.ACCEPTED

        round2_task = _nested_review_task(runtime)
        assert round2_task.state.next == ("finalize",)
        round2_interrupt_id = second.payload["user_interrupt"]["interrupt_id"]
        assert second.payload["user_interrupt"]["origin_target"] == "review.inspect"
        assert round2_interrupt_id != round1_interrupt_id

        # --- Round 3: resolved -- Review completes, run proceeds
        # downstream to WAITING_APPROVAL (ACTION plan + PASS). ---
        _queue_more(llm_runtime, [_review_output("PASS")])
        third = _resume_confirmation(
            runtime=runtime,
            database_path=database_path,
            resume_payload={
                "schema_version": 1,
                "interrupt_id": round2_interrupt_id,
                "response_kind": "FREE_TEXT",
                "selected_option": None,
                "free_text": "round-2 answer, resolves it.",
            },
            command_id="command-3",
        )
        assert third is not None
        assert third.outcome is WorkflowOutcome.ACCEPTED

        # No upstream re-execution at any point across rounds 2-3.
        assert _upstream_calls(llm_runtime) == upstream_before
        assert len(_review_calls(llm_runtime, "review.inspect")) == 3
    finally:
        runtime.close()


# --- T12: invalid resume fails closed. ---


def test_review_resume_rejects_wrong_interrupt_id(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-review-invalid.db"

    gateway = FakeGoogleGateway(snapshot)
    runtime, llm_runtime, _payload = _start_to_first_confirmation(
        database_path=database_path,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        llm_payloads=[
            *_ACTION_QUEUE_TO_REVIEW,
            _review_output("CONFIRM", confirmation=_confirmation()),
        ],
    )
    calls_before_resume = len(llm_runtime.calls)
    try:
        application_result, runtime_result = _attempt_confirmation(
            runtime=runtime,
            database_path=database_path,
            resume_payload={
                "schema_version": 1,
                "interrupt_id": "definitely-the-wrong-interrupt-id",
                "response_kind": "FREE_TEXT",
                "selected_option": None,
                "free_text": "irrelevant",
            },
            command_id="command-2",
        )
        assert application_result.applied is False  # type: ignore[attr-defined]
        assert runtime_result is None
        assert len(llm_runtime.calls) == calls_before_resume
    finally:
        runtime.close()


def test_review_resume_rejects_option_id_outside_allowed_scope(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    checkpoint_path = tmp_path / "checkpoints-review-invalid-option.db"

    gateway = FakeGoogleGateway(snapshot)
    runtime, llm_runtime, payload = _start_to_first_confirmation(
        database_path=database_path,
        gateway=gateway,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        llm_payloads=[
            *_ACTION_QUEUE_TO_REVIEW,
            _review_output("CONFIRM", confirmation=_confirmation()),
        ],
    )
    interrupt_id = payload["user_interrupt"]["interrupt_id"]
    assert payload["user_interrupt"]["options"] == []

    try:
        application_result, runtime_result = _attempt_confirmation(
            runtime=runtime,
            database_path=database_path,
            resume_payload={
                "schema_version": 1,
                "interrupt_id": interrupt_id,
                "response_kind": "OPTION",
                "selected_option": "option-not-offered",
                "free_text": None,
            },
            command_id="command-2",
        )
        assert application_result.applied is False  # type: ignore[attr-defined]
        assert "option" in (application_result.conflict_detail or "")  # type: ignore[attr-defined]
        assert runtime_result is None
    finally:
        runtime.close()


# --- T7: existing PASS -> Finalize (ANSWER target) happy path unaffected. ---


def test_review_pass_answer_target_completes(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[*_ANSWER_QUEUE_TO_REVIEW, _review_output("PASS")],
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


# --- T9: existing RETRIEVE_MORE -> Retrieval is a pure routing decision made
# by unchanged code (_finalize_resolved -> route_supervisor ->
# _route_plan_review's RETRIEVE_MORE branch, which this subgraph's new
# confirmation-interception guard cannot reach: the guard is gated on
# ``result["status"] == "CONFIRM"`` and always false here). Driving a full
# second Retrieval round through this integration runtime would only
# re-test Retrieval V2's own follow-up-round machinery (needs additional
# retrieval.plan_query queue items, out of C6's scope) -- already covered
# by tests/unit/application/workflows/test_supervisor.py and
# tests/unit/application/workflows/test_plan_review.py's own RETRIEVE_MORE
# cases (unchanged by C6).


# --- T11: existing BLOCK path unaffected. ---


def test_review_block_finalizes_blocked(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            *_ACTION_QUEUE_TO_REVIEW,
            _review_output("BLOCK", blockers=["The requested operation is prohibited."]),
        ],
        gateway=FakeGoogleGateway(snapshot),
        checkpoint_database_path=database_path,
        prompt_manifest_path=manifest_path,
    )
    try:
        result = start_with_admission(runtime, database_path, _start_write_request())
        assert result.outcome is WorkflowOutcome.COMPLETED
        connection = connect_sqlite(database_path)
        try:
            run_row = connection.execute("SELECT status FROM runs WHERE id = 'run-1';").fetchone()
            assert run_row[0] == "BLOCKED"
        finally:
            connection.close()
    finally:
        runtime.close()
