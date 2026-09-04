from copy import deepcopy
from typing import cast

import pytest

from google_work_agent.adapters.langgraph.main.state import (
    GraphState,
    GraphStateUpdateV1,
    WorkflowPhase,
)
from google_work_agent.adapters.langgraph.main.supervisor_artifact_revisions import (
    invalidate_stale_downstream,
)
from google_work_agent.adapters.langgraph.main.supervisor_decision import (
    SupervisorDecisionV1,
    SupervisorTarget,
    make_supervisor_decision,
)
from google_work_agent.adapters.langgraph.main.supervisor_progress import (
    guard_supervisor_no_progress,
    supervisor_progress_signature,
)
from google_work_agent.adapters.langgraph.main.supervisor_state_projection import (
    project_supervisor_state,
)
from google_work_agent.application.use_cases.run.get_supervisor_observation import (
    SupervisorObservationV1,
)


def test_intent_revision__with_existing_downstream__invalidates_all_artifacts() -> None:
    previous = _state()
    current = deepcopy(previous)
    cast(dict[str, object], current["request_intent"])["meta"] = _meta("intent-1", 2)

    invalidated = invalidate_stale_downstream(previous=previous, current=current)

    assert invalidated == [
        "tool_route_plan",
        "acquisition_result",
        "retrieval_result",
        "work_analysis_result",
        "planning_result",
        "plan_review",
        "approved_plan_id",
    ]
    assert all(current[field] is None for field in invalidated)


def test_retrieval_revision__with_existing_downstream__invalidates_dependent_artifacts() -> None:
    previous = _state()
    current = deepcopy(previous)
    cast(dict[str, object], current["retrieval_result"])["meta"] = _meta("retrieval-1", 2)

    invalidated = invalidate_stale_downstream(previous=previous, current=current)

    assert invalidated == [
        "work_analysis_result",
        "planning_result",
        "plan_review",
        "approved_plan_id",
    ]
    assert current["tool_route_plan"] is not None


@pytest.mark.parametrize(
    ("upstream", "expected"),
    [
        (
            "tool_route_plan",
            [
                "acquisition_result",
                "retrieval_result",
                "work_analysis_result",
                "planning_result",
                "plan_review",
                "approved_plan_id",
            ],
        ),
        ("work_analysis_result", ["planning_result", "plan_review", "approved_plan_id"]),
        ("planning_result", ["plan_review", "approved_plan_id"]),
    ],
)
def test_upstream_revision__with_existing_artifacts__invalidates_declared_descendants(
    upstream: str,
    expected: list[str],
) -> None:
    previous = _state()
    current = deepcopy(previous)
    artifact = current[upstream]
    if upstream == "tool_route_plan":
        artifact = cast(dict[str, object], artifact)["input_plan"]
    cast(dict[str, object], artifact)["meta"] = _meta(f"{upstream}-2", 2)

    invalidated = invalidate_stale_downstream(previous=previous, current=current)

    assert invalidated == expected
    assert all(current[field] is None for field in invalidated)


def test_upstream_revision__with_new_fresh_downstream__retains_new_artifacts() -> None:
    previous = _state()
    current = deepcopy(previous)
    cast(dict[str, object], current["planning_result"])["meta"] = _meta("plan-2", 1)
    cast(dict[str, object], current["plan_review"])["meta"] = {
        **_meta("review-2", 1),
        "based_on": [{"artifact_id": "plan-2", "revision": 1}],
    }

    invalidated = invalidate_stale_downstream(previous=previous, current=current)

    assert invalidated == ["approved_plan_id"]
    assert current["plan_review"] is not None
    assert current["approved_plan_id"] is None


def test_identical_back_edge__without_new_revision__fails_closed() -> None:
    state = _state()
    decision = _decision(SupervisorTarget.CONTEXT_RETRIEVAL, "EVIDENCE_GAP")
    signature = supervisor_progress_signature(state=state, decision=decision)
    state["trace_context"] = {
        "supervisor_decisions": [
            {
                "transition_kind": "BACK_EDGE",
                "progress_signature": signature,
            }
        ]
    }

    guarded = guard_supervisor_no_progress(state=state, decision=decision)

    assert guarded["target"] == SupervisorTarget.RECOVERY.value
    assert guarded["reason_code"] == "SUPERVISOR_NO_PROGRESS"


def test_supervisor_trace__records_stage_produced_revision_after_invalidation() -> None:
    state = _state()
    revised_intent = {"meta": _meta("intent-1", 2)}
    decision = make_supervisor_decision(
        target=SupervisorTarget.TOOL_ROUTE,
        next_phase=WorkflowPhase.TOOL_ROUTING,
        state_update={"workflow_phase": WorkflowPhase.TOOL_ROUTING.value},
        reason_code="INTENT_REVISED",
    )

    projection = project_supervisor_state(
        state=state,
        stage_update=cast(GraphStateUpdateV1, {"request_intent": revised_intent}),
        candidate=decision,
        durable_facts=SupervisorObservationV1(
            run_status="PLANNING",
            next_allowed_commands=(),
            action_statuses=(),
            cancel_intent_active=False,
        ),
    )

    trace = projection.state["trace_context"]["supervisor_decisions"][-1]
    assert "request_intent=intent-1:2" in trace["progress_signature"]
    assert trace["invalidated_fields"] == [
        "tool_route_plan",
        "acquisition_result",
        "retrieval_result",
        "work_analysis_result",
        "planning_result",
        "plan_review",
        "approved_plan_id",
    ]


def _state() -> GraphState:
    return cast(
        GraphState,
        {
            "workflow_phase": WorkflowPhase.PLAN_REVIEW.value,
            "request_intent": {"meta": _meta("intent-1", 1)},
            "tool_route_plan": {
                "input_plan": {"meta": _meta("input-1", 1)},
                "output_plan": {"meta": _meta("output-1", 1)},
            },
            "retrieval_result": {"meta": _meta("retrieval-1", 1)},
            "acquisition_result": {"status": "COMPLETE"},
            "work_analysis_result": {"meta": _meta("analysis-1", 1)},
            "planning_result": {"meta": _meta("plan-1", 1)},
            "plan_review": {"meta": _meta("review-1", 1)},
            "approved_plan_id": "approved-plan-1",
            "trace_context": {},
        },
    )


def _meta(artifact_id: str, revision: int) -> dict[str, object]:
    return {"artifact_id": artifact_id, "revision": revision, "based_on": []}


def _decision(target: SupervisorTarget, reason: str) -> SupervisorDecisionV1:
    return {
        "target": target.value,
        "next_phase": WorkflowPhase.CONTEXT_RETRIEVAL.value,
        "state_update": {"workflow_phase": WorkflowPhase.CONTEXT_RETRIEVAL.value},
        "reason_code": reason,
        "budget_decision": None,
    }
