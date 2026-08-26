from __future__ import annotations

from typing import cast

import pytest

from google_work_agent.application.orchestration.planning_argument_orchestrator import (
    RouteArgumentResult,
)
from google_work_agent.application.orchestration.planning_invocation import (
    PlanningV2Producer,
    PlanningV2RuntimeError,
)
from google_work_agent.ports import WorkflowStartRequest
from google_work_agent.ports.system.contracts.workflow_handoff import AgentNodeResumeTargetV2


class _AnswerProvider:
    calls = 0

    def draft_answer(self, **_kwargs):
        self.calls += 1
        return {"schema_version": 2, "answer": "done", "evidence_refs": ["ev-1"]}


class _NoActionOrchestrator:
    def prepare_actions(self, **_kwargs):
        raise AssertionError("ANSWER path must not prepare actions")

    def compose_prepared(self, **_kwargs):
        raise AssertionError("ANSWER path must not compose actions")


class _ActionOrchestrator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def prepare_actions(self, *, output_routes):
        self.calls.append("prepare_actions")
        route = output_routes[0]
        return (
            {
                "disposition": "READY",
                "route_id": route["route_id"],
                "bound_tool_schema": {
                    "route_id": route["route_id"],
                    "connector_id": route["connector_id"],
                    "resource_type": route["resource_type"],
                    "effect": route["effect"],
                    "selected_tool_id": route["selected_tool_id"],
                    "argument_schema": {},
                    "deterministic_arguments": {},
                },
            },
        )

    def compose_prepared(self, *, output_routes, **_kwargs):
        self.calls.append("compose_prepared")
        route = output_routes[0]
        return (
            RouteArgumentResult(
                route=route,
                bound_tool_schema={},
                candidate={
                    "schema_version": 1,
                    "route_id": route["route_id"],
                    "arguments": {"task_id": "task-1", "task_list_id": "list-1"},
                    "evidence_refs": ["ev-1"],
                },
                llm_result=None,
            ),
        )

    def compose(self, **_kwargs):
        raise AssertionError("legacy compose() must never be V2 ACTION authority")


class _ConfirmationOrchestrator:
    def prepare_actions(self, *, output_routes):
        return (
            {
                "disposition": "NEEDS_CONFIRMATION",
                "route_id": output_routes[0]["route_id"],
                "question": "Choose the task list",
                "options": [],
                "reason_codes": ["PLANNING_REQUIRED_CONTAINER_UNRESOLVED"],
            },
        )

    def compose_prepared(self, **_kwargs):
        raise AssertionError("non-ready preparation must not invoke writer")


class _UnusedAnswerProvider:
    def draft_answer(self, **_kwargs):
        raise AssertionError("ACTION path must not draft answer")


def _intent():
    return {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 2, "based_on": []},
        "goal": "update task",
        "completion_conditions": [],
        "constraints": [],
        "requested_effect_hints": ["UPDATE"],
        "requested_resource_hints": ["TASK"],
        "analysis_requirement": "REQUIRED",
        "ambiguity": {
            "requires_confirmation": False,
            "reason_codes": [],
            "missing_fields": [],
        },
    }


def _retrieval():
    return {
        "schema_version": 1,
        "meta": {
            "artifact_id": "retrieval-1",
            "revision": 3,
            "based_on": [{"artifact_id": "route-input-1", "revision": 1}],
        },
        "coverage": "SUFFICIENT",
        "context_bundle_ref": "context-1",
        "evidence_refs": ["ev-1"],
        "selected_segment_ids": ["seg-1"],
        "source_resource_refs": ["task:task-1"],
        "source_statuses": [],
        "missing_information": [],
        "retrieval_rounds": 1,
    }


def _analysis():
    return {
        "schema_version": 2,
        "meta": {
            "artifact_id": "analysis-1",
            "revision": 4,
            "based_on": [{"artifact_id": "retrieval-1", "revision": 3}],
        },
        "work_facts": [],
        "relations": [],
        "ambiguities": [],
        "risks": [],
        "evidence_refs": ["ev-1"],
        "policy_confirmation_receipt_refs": [],
        "action_necessity": "REQUIRED",
    }


def _evidence():
    return [
        {
            "schema_version": 1,
            "evidence_id": "ev-1",
            "resource_handle": "task:task-1",
            "segment_id": "seg-1",
            "kind": "excerpt",
            "excerpt": "task",
            "locator": None,
            "reason_codes": ["SUPPORTS"],
        }
    ]


def _route(*, mode: str):
    output_plan = {
        "schema_version": 1,
        "meta": {
            "artifact_id": "route-output-1",
            "revision": 5,
            "based_on": [{"artifact_id": "intent-1", "revision": 2}],
        },
        "output_mode": mode,
    }
    if mode == "ACTION":
        output_plan["output_routes"] = [
            {
                "route_id": "route-1",
                "resource_type": "TASK",
                "connector_id": "google-primary",
                "effect": "UPDATE",
                "selected_tool_id": "tasks_update_task",
                "reason_codes": ["REQUESTED_OUTPUT"],
            }
        ]
    return {
        "schema_version": 2,
        "input_plan": {
            "schema_version": 1,
            "meta": {"artifact_id": "route-input-1", "revision": 1, "based_on": []},
            "input_routes": [],
        },
        "output_plan": output_plan,
        "tool_registry_version": "test",
    }


def _request():
    return cast(WorkflowStartRequest, object())


def test_answer_promotes_v2_artifact_with_exact_current_lineage() -> None:
    provider = _AnswerProvider()
    producer = PlanningV2Producer(
        answer_candidate_provider=provider,
        argument_orchestrator=cast(object, _NoActionOrchestrator()),
        artifact_id_factory=lambda: "answer-1",
        action_id_factory=lambda: "unused",
    )
    result = producer.run(
        request=_request(),
        request_intent=_intent(),
        tool_route_plan=_route(mode="ANSWER"),
        retrieval_result=_retrieval(),
        work_analysis_result=_analysis(),
        evidence_drafts=_evidence(),
    )
    assert result["disposition"] == "ANSWER_ONLY"
    assert result["workflow_signal"] is None
    assert result["typed_result"]["schema_version"] == 2
    assert result["typed_result"]["meta"]["based_on"] == [
        {"artifact_id": "route-output-1", "revision": 5},
        {"artifact_id": "analysis-1", "revision": 4},
        {"artifact_id": "retrieval-1", "revision": 3},
    ]
    assert provider.calls == 1


def test_action_uses_prepare_then_compose_prepared_and_never_legacy_compose() -> None:
    orchestrator = _ActionOrchestrator()
    producer = PlanningV2Producer(
        answer_candidate_provider=_UnusedAnswerProvider(),
        argument_orchestrator=cast(object, orchestrator),
        artifact_id_factory=lambda: "plan-1",
        action_id_factory=lambda: "action-1",
    )
    result = producer.run(
        request=_request(),
        request_intent=_intent(),
        tool_route_plan=_route(mode="ACTION"),
        retrieval_result=_retrieval(),
        work_analysis_result=_analysis(),
        evidence_drafts=_evidence(),
    )
    assert orchestrator.calls == ["prepare_actions", "compose_prepared"]
    assert result["disposition"] == "PLAN_READY"
    assert result["typed_result"]["actions"][0]["tool_id"] == "tasks_update_task"
    assert result["typed_result"]["actions"][0]["effect"] == "UPDATE"


def test_action_confirmation_carries_no_partial_planning_artifact() -> None:
    producer = PlanningV2Producer(
        answer_candidate_provider=_UnusedAnswerProvider(),
        argument_orchestrator=cast(object, _ConfirmationOrchestrator()),
        artifact_id_factory=lambda: "must-not-be-used",
        action_id_factory=lambda: "must-not-be-used",
    )
    result = producer.run(
        request=_request(),
        request_intent=_intent(),
        tool_route_plan=_route(mode="ACTION"),
        retrieval_result=_retrieval(),
        work_analysis_result=_analysis(),
        evidence_drafts=_evidence(),
        interrupt_id="interrupt-1",
        resume_target=AgentNodeResumeTargetV2(
            kind="AGENT_NODE",
            semantic_owner_id="PLANNING",
            compiled_subgraph_id="SIX_PLANNING",
            node_id="planning.compose_arguments_per_output_route",
            graph_profile="SIX_ROLE_BASELINE",
            graph_version="runtime-v2",
        ),
    )
    assert result["disposition"] == "NEEDS_CONFIRMATION"
    assert result["typed_result"] is None
    assert result["workflow_signal"]["kind"] == "CONFIRMATION_REQUIRED"
    assert result["workflow_signal"]["semantic_owner_id"] == "PLANNING"


def test_semantic_route_reconsideration_carries_no_partial_artifact() -> None:
    producer = PlanningV2Producer(
        answer_candidate_provider=_UnusedAnswerProvider(),
        argument_orchestrator=cast(object, _NoActionOrchestrator()),
        artifact_id_factory=lambda: "must-not-be-used",
        action_id_factory=lambda: "must-not-be-used",
    )
    result = producer.run(
        request=_request(),
        request_intent=_intent(),
        tool_route_plan=_route(mode="ANSWER"),
        retrieval_result=_retrieval(),
        work_analysis_result=_analysis(),
        evidence_drafts=_evidence(),
        semantic_control={
            "disposition": "ROUTE_RECONSIDERATION_REQUIRED",
            "reason_codes": ["ROUTE_NO_LONGER_VALID"],
        },
    )
    assert result["typed_result"] is None
    assert result["workflow_signal"] == {
        "kind": "ROUTE_RECONSIDERATION_REQUIRED",
        "reason_codes": ["ROUTE_NO_LONGER_VALID"],
    }


def test_stale_work_analysis_is_rejected_before_candidate_generation() -> None:
    stale = _analysis()
    stale["meta"] = {
        "artifact_id": "analysis-1",
        "revision": 4,
        "based_on": [{"artifact_id": "retrieval-1", "revision": 2}],
    }
    producer = PlanningV2Producer(
        answer_candidate_provider=_AnswerProvider(),
        argument_orchestrator=cast(object, _NoActionOrchestrator()),
        artifact_id_factory=lambda: "answer-1",
        action_id_factory=lambda: "unused",
    )
    with pytest.raises(PlanningV2RuntimeError, match="stale WorkAnalysisResultV2"):
        producer.run(
            request=_request(),
            request_intent=_intent(),
            tool_route_plan=_route(mode="ANSWER"),
            retrieval_result=_retrieval(),
            work_analysis_result=stale,
            evidence_drafts=_evidence(),
        )
