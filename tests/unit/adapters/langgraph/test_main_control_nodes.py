from __future__ import annotations

from dataclasses import dataclass

import pytest

from google_work_agent.adapters.langgraph.main.nodes.domain_reconcile_node import (
    domain_reconcile_node,
)
from google_work_agent.adapters.langgraph.main.nodes.domain_validation_node import (
    domain_validation_node,
)
from google_work_agent.adapters.langgraph.main.nodes.initialize_node import initialize_node
from google_work_agent.adapters.langgraph.main.nodes.planning_entry_node import (
    planning_entry_node,
)
from google_work_agent.adapters.langgraph.main.nodes.preflight_node import preflight_node
from google_work_agent.adapters.langgraph.main.nodes.retrieval_entry_node import (
    retrieval_entry_node,
)
from google_work_agent.adapters.langgraph.main.nodes.review_entry_node import (
    review_entry_node,
)
from google_work_agent.application.use_cases.run.begin_planning import BeginPlanningResult
from google_work_agent.application.use_cases.run.begin_retrieval import BeginRetrievalResult
from google_work_agent.application.use_cases.run.start_analysis import StartAnalysisResult


@dataclass
class _RunFacts:
    status: str
    next_allowed_commands: tuple[str, ...]


def test_initialize_projects__start_analysis_without__copying_foreign_state() -> None:
    patch = initialize_node(
        {"run_id": "run-1", "foreign": "keep"},
        start_analysis=lambda _run_id: StartAnalysisResult(True, "APPLIED", "ANALYZING", 1, ()),
        request_node="request_understanding",
    )

    assert patch == {
        "workflow_phase": "REQUEST_ANALYSIS",
        "__logical_target__": "request_understanding",
        "__target__": "request_understanding",
    }
    assert "foreign" not in patch


def test_retrieval_entry_requires__frozen_routes_and__routes_registered_subgraph() -> None:
    state = {
        "run_id": "run-1",
        "tool_route_plan": {"input_plan": {"input_routes": [{"route_id": "r1"}]}},
    }
    patch = retrieval_entry_node(
        state,
        current_run_status=lambda _run_id: "ANALYZING",
        begin_retrieval=lambda _run_id: BeginRetrievalResult(True, "APPLIED", "RETRIEVING", 1, ()),
        retrieval_node="context_retriever",
    )

    assert patch["__target__"] == "context_retriever"
    assert patch["workflow_phase"] == "CONTEXT_RETRIEVAL"

    with pytest.raises(ValueError, match="frozen tool_route_plan"):
        retrieval_entry_node(
            {"run_id": "run-1"},
            current_run_status=lambda _run_id: "ANALYZING",
            begin_retrieval=lambda _run_id: BeginRetrievalResult(
                True, "APPLIED", "RETRIEVING", 1, ()
            ),
            retrieval_node="context_retriever",
        )


def test_planning_entry__fails_closed_on__illegal_durable_status() -> None:
    patch = planning_entry_node(
        {"run_id": "run-1"},
        current_run_status=lambda _run_id: "WAITING_APPROVAL",
        begin_planning=lambda _run_id: BeginPlanningResult(
            False, "REJECTED", "WAITING_APPROVAL", 1, ()
        ),
        planning_node="planning",
    )

    assert patch == {
        "__logical_target__": "domain_reconcile",
        "__target__": "domain_reconcile",
    }


def test_review_entry__routes_then__settles_persisted_review() -> None:
    initial = {
        "approved_plan_id": "plan-1",
        "__modify_review_plan_id__": "plan-1",
    }
    entered = review_entry_node(
        initial,
        prepare_persisted_review=lambda state: state,
        settle_persisted_review=lambda state: state,
        review_node="review",
    )

    assert entered["__target__"] == "review"
    assert entered["__workflow_control__"] == {
        "schema_version": 1,
        "stage": "REVIEW_PENDING_SETTLEMENT",
    }

    settled = review_entry_node(
        {**initial, **entered, "__target__": "domain_validation"},
        prepare_persisted_review=lambda state: state,
        settle_persisted_review=lambda _state: {"__target__": "planning_entry"},
        review_node="review",
    )
    assert settled == {
        "__target__": "planning_entry",
        "__workflow_control__": None,
    }


def test_review_entry_does__not_reload_persisted_plan__for_fresh_replan_draft() -> None:
    state = {
        "approved_plan_id": "plan-1",
        "__replan_from_plan_id__": "plan-1",
        "planning_result": {"schema_version": 2, "kind": "ACTION"},
    }

    entered = review_entry_node(
        state,
        prepare_persisted_review=lambda _state: (_ for _ in ()).throw(
            AssertionError("fresh replan review must not reload the superseded plan")
        ),
        settle_persisted_review=lambda current: current,
        review_node="review",
    )

    assert entered["__target__"] == "review"
    assert "__workflow_control__" not in entered


def test_validation_and_preflight__reject_unregistered_targets__and_return_patches() -> None:
    assert domain_validation_node(
        {"foreign": "keep"},
        validate_and_project=lambda _state: {"__target__": "preflight"},
    ) == {"__target__": "preflight"}
    assert preflight_node(
        {"foreign": "keep"},
        check_freshness_and_claim=lambda _state: {
            "foreign": "keep",
            "__target__": "action_execution",
        },
    ) == {"__target__": "action_execution"}

    with pytest.raises(ValueError, match="unregistered target"):
        domain_validation_node({}, validate_and_project=lambda _state: {"__target__": "unknown"})
    with pytest.raises(ValueError, match="unregistered target"):
        preflight_node({}, check_freshness_and_claim=lambda _state: {"__target__": "unknown"})


def test_domain_reconcile_uses__only_durable_status__and_allowed_commands() -> None:
    assert domain_reconcile_node(
        {"run_id": "run-1", "workflow_phase": "ACTION_EXECUTION"},
        read_durable_run=lambda _run_id: _RunFacts("RECOVERY_REQUIRED", ("RESOLVE_RECOVERY",)),
    ) == {
        "workflow_phase": "RECOVERY",
        "__logical_target__": "recovery",
        "__target__": "recovery",
    }
    suspended = domain_reconcile_node(
        {"run_id": "run-1"},
        read_durable_run=lambda _run_id: None,
    )
    assert suspended["__target__"] == "end"
