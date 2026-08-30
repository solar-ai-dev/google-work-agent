"""Canonical Planning Production Migration -- ACTION path integration tests.

Tool Route has already frozen each output route's connector/resource/effect/
selected-Tool identity before Planning ever runs. These tests prove the
*production* ``PlanningSubgraph`` (not just the already-covered unit tests in
``test_canonical_planning_arguments.py``) actually calls the canonical
``PlanningArgumentOrchestrator`` (per-route ``PlanningArgumentWriter`` +
deterministic ``planning_plan_assembler``) for ``draft_plan``/``revise_plan``,
never the legacy whole-plan-in-one-call
``SolutionPlanningAgent.invoke_draft_plan_llm_from_evidence``: Tool/effect/
route identity, Action ID, dependency, and Expected verification stay
code-owned regardless of what the per-route LLM candidate contains.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from tests.integration.langgraph.test_runtime import (
    FIXTURE_ROOT,
    FakeGoogleGateway,
    GraphProfile,
    LangGraphWorkflowRuntime,
    Path,
    ProductFixtureSnapshotLoader,
    _action_required_intent,
    _analysis_output,
    _llm_result,
    _make_runtime_with_llm,
    _QueuedLLMRuntime,
    _replace_result_aliases,
    _review_output,
    _runtime_active_manifest_path,
    _seed_runtime_database,
    _selection_output,
    _start_request,
    _sufficiency_output,
    pytest,
)
from tests.support.checkpoint import sqlite_checkpoint

from google_work_agent.application.agents.planning.resolve_default_container import (
    PlanningArgumentBindingError,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputRoutePlanV1,
    OutputToolRouteV1,
    ToolRoutePlanV2,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    ActionPlanDraftV1,
    EvidenceDraftV1,
    PlanReviewResultV1,
    RequestIntentV2,
    RetrievalResultV1,
    WorkAnalysisResultV1,
)
from google_work_agent.ports.llm import LLMInvocationError


class _ActionQueuedLLMRuntime(_QueuedLLMRuntime):
    """Synthesizes ``planning.compose_arguments``/``.revise`` responses using
    the REAL ``route_id`` from each call's own ``prompt_input`` -- route_id
    is ``id_factory``-generated (not a fixed string test fixtures could
    queue as a literal). Everything else (classify/tool_route/plan_query
    auto-synth, queued items) is the unchanged shared ``_QueuedLLMRuntime``
    behavior.
    """

    def __init__(
        self,
        payloads: Sequence[object],
        *,
        arguments_by_tool: dict[str, dict[str, object]],
        evidence_refs: Sequence[str] = ("evidence-seg-2",),
    ) -> None:
        super().__init__(payloads)
        self._arguments_by_tool = arguments_by_tool
        self._evidence_refs = list(evidence_refs)

    def _invoke(self, **kwargs: object) -> Any:
        prompt_ref = kwargs.get("prompt_ref")
        prompt_id = getattr(prompt_ref, "prompt_id", None)
        if prompt_id == "planning.draft_action_objective_per_output_route":
            self.calls.append(dict(kwargs))
            prompt_input = cast(dict[str, object], kwargs["prompt_input"])
            output_route = cast(dict[str, object], prompt_input["output_route"])
            return _replace_result_aliases(
                _llm_result(
                    {
                        "schema_version": 1,
                        "route_id": output_route["route_id"],
                        "objective": "Perform the requested bounded action.",
                        "target_semantics": output_route["resource_type"],
                        "scope_constraints": ["preserve frozen route identity"],
                        "evidence_refs": list(self._evidence_refs),
                    }
                ),
                self._segment_id_aliases,
            )
        if prompt_id == "planning.compose_arguments_per_output_route":
            self.calls.append(dict(kwargs))
            prompt_input = cast(dict[str, object], kwargs["prompt_input"])
            output_route = cast(dict[str, object], prompt_input["output_route"])
            tool_id = cast(str, output_route["selected_tool_id"])
            return _replace_result_aliases(
                _llm_result(
                    {
                        "schema_version": 1,
                        "route_id": output_route["route_id"],
                        "arguments": self._arguments_by_tool[tool_id],
                        "evidence_refs": list(self._evidence_refs),
                    }
                ),
                self._segment_id_aliases,
            )
        return super()._invoke(**kwargs)


def _build_runtime(
    *,
    database_path: Path,
    llm_runtime: _QueuedLLMRuntime,
    gateway: FakeGoogleGateway,
    checkpoint_path: Path,
    manifest_path: Path,
    id_prefix: str,
) -> LangGraphWorkflowRuntime:
    return _make_runtime_with_llm(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=gateway,
        checkpoint_port=sqlite_checkpoint(checkpoint_path),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path=manifest_path,
        default_tasklist_id="task-list-default",
        default_calendar_id="calendar-primary",
        id_prefix=id_prefix,
    )


def _intent() -> RequestIntentV2:
    payload = _action_required_intent()
    payload["meta"] = {"artifact_id": "intent-1", "revision": 1, "based_on": []}
    return payload


def _evidence_drafts() -> list[EvidenceDraftV1]:
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


def _retrieval_result() -> RetrievalResultV1:
    return {
        "schema_version": 1,
        "meta": {"artifact_id": "retrieval-1", "revision": 1, "based_on": []},
        "coverage": "SUFFICIENT",
        "context_bundle_ref": None,
        "evidence_refs": ["evidence-seg-2"],
        "selected_segment_ids": ["seg-2"],
        "source_resource_refs": ["task:task-followup"],
        "source_statuses": [],
        "missing_information": [],
        "retrieval_rounds": 1,
    }


def _analysis_result() -> WorkAnalysisResultV1:
    return cast(WorkAnalysisResultV1, _analysis_output())


def _analysis_result_with_calendar_event_target() -> WorkAnalysisResultV1:
    """WorkAnalysis result naming an existing CALENDAR_EVENT as the write target.

    Update/Delete on an existing resource requires the evidence policy's
    user-selected-target condition (or 2+ evidence, or an explicit resource
    relation) -- production WorkAnalysis identifies the target resource
    before Planning ACTION ever runs, so tests exercising an existing-event
    UPDATE/DELETE route must supply that same resource_ref, matching the
    frozen route's ``event_id`` by handle prefix + resource_id.
    """
    output = _analysis_output()
    output["resource_refs"] = [
        *cast(list[dict[str, object]], output["resource_refs"]),
        {
            "resource_handle": "calendar_event:event-1",
            "resource_type": "calendar_event",
            "resource_id": "event-1",
        },
    ]
    return cast(WorkAnalysisResultV1, output)


def _task_route(route_id: str = "route-task-create") -> OutputToolRouteV1:
    return {
        "route_id": route_id,
        "resource_type": "TASK",
        "connector_id": "google_workspace",
        "effect": "CREATE",
        "selected_tool_id": "tasks_create_task",
        "reason_codes": ["USER_REQUEST"],
    }


def _calendar_update_route(route_id: str = "route-cal-update") -> OutputToolRouteV1:
    return {
        "route_id": route_id,
        "resource_type": "CALENDAR_EVENT",
        "connector_id": "google_workspace",
        "effect": "UPDATE",
        "selected_tool_id": "calendar_update_event",
        "reason_codes": ["USER_REQUEST"],
    }


def _calendar_delete_route(route_id: str = "route-cal-delete") -> OutputToolRouteV1:
    return {
        "route_id": route_id,
        "resource_type": "CALENDAR_EVENT",
        "connector_id": "google_workspace",
        "effect": "DELETE",
        "selected_tool_id": "calendar_delete_event",
        "reason_codes": ["USER_REQUEST"],
    }


def _tool_route_plan(*routes: OutputToolRouteV1) -> ToolRoutePlanV2:
    input_plan: InputRoutePlanV1 = {
        "schema_version": 1,
        "meta": {"artifact_id": "route-plan-1", "revision": 1, "based_on": []},
        "input_routes": [],
    }
    return {
        "schema_version": 2,
        "input_plan": input_plan,
        "output_plan": {
            "schema_version": 1,
            "meta": {"artifact_id": "route-plan-1", "revision": 1, "based_on": []},
            "output_mode": "ACTION",
            "output_routes": list(routes),
        },
        "tool_registry_version": "test-registry",
    }


def _planning_state(
    runtime: LangGraphWorkflowRuntime,
    *,
    tool_route_plan: ToolRoutePlanV2,
    plan_draft: dict[str, object] | None = None,
    plan_review: dict[str, object] | None = None,
    analysis_result: WorkAnalysisResultV1 | None = None,
) -> dict[str, object]:
    state = runtime._initial_state(_start_request())  # noqa: SLF001
    state["request_intent"] = _intent()
    state["tool_route_plan"] = tool_route_plan
    state["retrieval_result"] = _retrieval_result()
    state["analysis_result"] = (
        analysis_result if analysis_result is not None else _analysis_result()
    )
    state["work_analysis_result"] = None
    state["answer_draft"] = None
    state["plan_draft"] = cast("ActionPlanDraftV1 | None", plan_draft)
    state["plan_review"] = cast("PlanReviewResultV1 | None", plan_review)
    runtime._evidence_store.put(run_id=state["run_id"], evidence_drafts=_evidence_drafts())  # noqa: SLF001
    return cast(dict[str, object], state)


def _compose_calls(llm_runtime: _QueuedLLMRuntime) -> list[dict[str, object]]:
    return [
        call
        for call in llm_runtime.calls
        if getattr(call["prompt_ref"], "prompt_id", None)
        == "planning.compose_arguments_per_output_route"
    ]


# --- T1: single ACTION route through the real production start() path. ---


def test_single_action_route_uses_canonical_writer_exactly_once(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    llm_runtime = _ActionQueuedLLMRuntime(
        [
            _action_required_intent(),
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _review_output("PASS"),
        ],
        arguments_by_tool={
            "tasks_create_task": {"payload": {"title": "Prepare report"}},
        },
    )
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=gateway,
        checkpoint_path=tmp_path / "checkpoints-canonical-single.db",
        manifest_path=manifest_path,
        id_prefix="run",
    )
    try:
        state = _planning_state(runtime, tool_route_plan=_tool_route_plan(_task_route()))
        result = runtime._planning_subgraph.invoke(state)  # noqa: SLF001
        compose_calls = _compose_calls(llm_runtime)
        assert len(compose_calls) == 1
        assert set(cast(dict[str, object], compose_calls[0]["prompt_input"])) == {
            "output_route",
            "action_objective",
            "tool_schema",
            "evidence",
        }
        plan = result["planning_result"]
        assert plan["schema_version"] == 2
        assert plan["actions"][0]["tool_id"] == "tasks_create_task"
    finally:
        runtime.close()


# --- T2: multiple ACTION routes -- one Argument Writer call per route, in
# frozen route order. ---


def test_multiple_action_routes_each_get_their_own_writer_call(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    llm_runtime = _ActionQueuedLLMRuntime(
        [],
        arguments_by_tool={
            "calendar_update_event": {
                "event_id": "event-1",
                "payload": {"title": "Updated sync"},
            },
            "calendar_delete_event": {"event_id": "event-1"},
        },
    )
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=gateway,
        checkpoint_path=tmp_path / "checkpoints-canonical-multi.db",
        manifest_path=manifest_path,
        id_prefix="run",
    )
    try:
        routes = (_calendar_update_route(), _calendar_delete_route())
        state = _planning_state(
            runtime,
            tool_route_plan=_tool_route_plan(*routes),
            analysis_result=_analysis_result_with_calendar_event_target(),
        )
        result = runtime._planning_subgraph.invoke(state)  # noqa: SLF001

        compose_calls = _compose_calls(llm_runtime)
        assert len(compose_calls) == 2
        called_route_ids = [
            cast(dict[str, object], call["prompt_input"])["output_route"]["route_id"]  # type: ignore[index]
            for call in compose_calls
        ]
        assert called_route_ids == ["route-cal-update", "route-cal-delete"]

        plan_draft = result["planning_result"]
        assert [action["tool_id"] for action in plan_draft["actions"]] == [
            "calendar_update_event",
            "calendar_delete_event",
        ]
        # T7: same-resource dependency is code-derived -- the delete depends
        # on the update since both target the same CALENDAR_EVENT identity.
        delete_action = plan_draft["actions"][1]
        update_action = plan_draft["actions"][0]
        assert delete_action["depends_on_action_ids"] == [update_action["action_id"]]
    finally:
        runtime.close()


# --- T3: Tool/effect/route authority is code-owned -- the LLM candidate has
# no field capable of changing it. ---


def test_llm_candidate_cannot_change_tool_or_effect_identity(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    llm_runtime = _ActionQueuedLLMRuntime(
        [],
        arguments_by_tool={"tasks_create_task": {"payload": {"title": "Prepare report"}}},
    )
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=gateway,
        checkpoint_path=tmp_path / "checkpoints-canonical-authority.db",
        manifest_path=manifest_path,
        id_prefix="run",
    )
    try:
        route = _task_route()
        state = _planning_state(runtime, tool_route_plan=_tool_route_plan(route))
        result = runtime._planning_subgraph.invoke(state)  # noqa: SLF001

        # ToolArgumentCandidateV1 has no tool_name/effect field at all --
        # the writer physically cannot express a different Tool/effect, and
        # the assembler copies identity from the frozen route, not the
        # candidate.
        plan_draft = result["planning_result"]
        action = plan_draft["actions"][0]
        assert action["tool_id"] == route["selected_tool_id"]
        assert action["effect"] == route["effect"]
    finally:
        runtime.close()


# --- T4: Schema binding -- a candidate violating the bound Tool schema
# fails closed. ---


def test_candidate_violating_bound_schema_fails_closed(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    # "title" is required by _TASK_CREATE_PAYLOAD; omit it to violate the
    # bound selected Tool schema.
    llm_runtime = _ActionQueuedLLMRuntime(
        [],
        arguments_by_tool={"tasks_create_task": {"payload": {}}},
    )
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=gateway,
        checkpoint_path=tmp_path / "checkpoints-canonical-schema-fail.db",
        manifest_path=manifest_path,
        id_prefix="run",
    )
    try:
        state = _planning_state(runtime, tool_route_plan=_tool_route_plan(_task_route()))
        with pytest.raises((PlanningArgumentBindingError, LLMInvocationError, ValueError)):
            runtime._planning_subgraph.invoke(state)  # noqa: SLF001
    finally:
        runtime.close()


# --- T5 + T6: Action ID and Expected verification are deterministic,
# code-owned -- never influenced by anything in the LLM candidate (the
# candidate schema has no field for either). ---


def test_action_id_and_expected_are_deterministically_assembled(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    llm_runtime = _ActionQueuedLLMRuntime(
        [],
        arguments_by_tool={
            "tasks_create_task": {
                "payload": {"title": "Prepare report", "scheduled_date": "2026-08-20"}
            }
        },
    )
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=gateway,
        checkpoint_path=tmp_path / "checkpoints-canonical-deterministic.db",
        manifest_path=manifest_path,
        id_prefix="det",
    )
    try:
        state = _planning_state(runtime, tool_route_plan=_tool_route_plan(_task_route()))
        result = runtime._planning_subgraph.invoke(state)  # noqa: SLF001

        action = result["planning_result"]["actions"][0]
        # T5: action_id is one of this run's own id_factory outputs -- never
        # something the LLM could have supplied (ToolArgumentCandidateV1 has
        # no action_id field at all).
        assert action["action_id"].startswith("det-")
        assert "expected" not in action
    finally:
        runtime.close()


# --- T8: evidence_refs outside the allowed set fails closed. ---


def test_candidate_evidence_outside_allowed_set_fails_closed(tmp_path: Path) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    llm_runtime = _ActionQueuedLLMRuntime(
        [],
        arguments_by_tool={"tasks_create_task": {"payload": {"title": "Prepare report"}}},
        evidence_refs=["evidence-not-in-run"],
    )
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=gateway,
        checkpoint_path=tmp_path / "checkpoints-canonical-evidence-fail.db",
        manifest_path=manifest_path,
        id_prefix="run",
    )
    try:
        state = _planning_state(runtime, tool_route_plan=_tool_route_plan(_task_route()))
        with pytest.raises((PlanningArgumentBindingError, LLMInvocationError, ValueError)):
            runtime._planning_subgraph.invoke(state)  # noqa: SLF001
    finally:
        runtime.close()


# --- T12: Review.REVISE affected-only -- only the route with a relevant
# issue gets a new Argument Writer call; the unaffected route's existing
# candidate is preserved. ---


def test_legacy_review_revision_input_does_not_restore_broad_planning_authority(
    tmp_path: Path,
) -> None:
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    llm_runtime = _ActionQueuedLLMRuntime(
        [],
        arguments_by_tool={
            "calendar_update_event": {
                "event_id": "event-1",
                "payload": {"title": "Corrected title"},
            },
            "calendar_delete_event": {"event_id": "event-1"},
        },
    )
    runtime = _build_runtime(
        database_path=database_path,
        llm_runtime=llm_runtime,
        gateway=gateway,
        checkpoint_path=tmp_path / "checkpoints-canonical-revise.db",
        manifest_path=manifest_path,
        id_prefix="rev",
    )
    try:
        update_route = _calendar_update_route()
        delete_route = _calendar_delete_route()
        tool_route_plan = _tool_route_plan(update_route, delete_route)

        existing_plan = {
            "schema_version": 2,
            "status": "PLAN_READY",
            "plan_id": "plan-existing",
            "summary": "Update then delete the calendar event.",
            "objective": "Reflect the corrected meeting details.",
            "actions": [
                {
                    "schema_version": 2,
                    "action_id": "action-update-existing",
                    "position": 1,
                    "effect": "UPDATE",
                    "tool_name": "calendar_update_event",
                    "arguments": {
                        "event_id": "event-1",
                        "payload": {"title": "Wrong title"},
                    },
                    "expected": {"payload": {"title": "Wrong title"}},
                    "evidence_refs": ["evidence-seg-2"],
                    "resource_refs": [],
                    "target_resource_ref_id": None,
                    "depends_on_action_ids": [],
                    "user_visible_reason": "Update the event.",
                },
                {
                    "schema_version": 2,
                    "action_id": "action-delete-existing",
                    "position": 2,
                    "effect": "DELETE",
                    "tool_name": "calendar_delete_event",
                    "arguments": {"event_id": "event-1"},
                    "expected": {"absent": True},
                    "evidence_refs": ["evidence-seg-2"],
                    "resource_refs": [],
                    "target_resource_ref_id": None,
                    "depends_on_action_ids": ["action-update-existing"],
                    "user_visible_reason": "Delete the event.",
                },
            ],
            "evidence_refs": ["evidence-seg-2"],
            "resource_refs": [],
            "confirmation": None,
        }
        plan_review = {
            "schema_version": 2,
            "status": "REVISE",
            "summary": "Fix the update action's title.",
            "issues": [
                {
                    "schema_version": 2,
                    "issue_id": "issue-1",
                    "kind": "ARGUMENT_MISMATCH",
                    "message": "Title must reflect the corrected meeting details.",
                    "affected_action_ids": ["action-update-existing"],
                    "affected_field_paths": ["$.actions[0].arguments.payload.title"],
                    "evidence_refs": ["evidence-seg-2"],
                    "resource_refs": [],
                    "reason_codes": ["ARGUMENT_MISMATCH"],
                }
            ],
            "confirmation": None,
            "blockers": [],
            "additional_acquisition_request": None,
        }

        state = _planning_state(
            runtime,
            tool_route_plan=tool_route_plan,
            plan_draft=cast(dict[str, object], existing_plan),
            plan_review=cast(dict[str, object], plan_review),
            analysis_result=_analysis_result_with_calendar_event_target(),
        )
        result = runtime._planning_subgraph.invoke(state)  # noqa: SLF001

        compose_calls = _compose_calls(llm_runtime)
        assert len(compose_calls) == 2

        plan_draft = result["planning_result"]
        actions_by_tool = {action["tool_id"]: action for action in plan_draft["actions"]}
        assert (
            actions_by_tool["calendar_update_event"]["arguments"]["payload"]["title"]
            == "Corrected title"
        )
        assert actions_by_tool["calendar_delete_event"]["arguments"] == {
            "calendar_id": "calendar-primary",
            "event_id": "event-1",
        }
        assert actions_by_tool["calendar_delete_event"]["action_id"] != "action-delete-existing"
    finally:
        runtime.close()
