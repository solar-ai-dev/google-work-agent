from __future__ import annotations

import pytest

from google_work_agent.application.orchestration.review_invocation import (
    ReviewV2Producer,
    ReviewV2RuntimeError,
)
from google_work_agent.ports.system.contracts.workflow_handoff import AgentNodeResumeTargetV2


class _PassProvider:
    def inspect(self, **_kwargs):
        return {"schema_version": 2, "status": "PASS", "summary": "safe"}


class _ConfirmProvider:
    def inspect(self, **_kwargs):
        return {
            "schema_version": 2,
            "status": "CONFIRM",
            "confirmation": {
                "reason_code": "USER_CHOICE_REQUIRED",
                "question": "Proceed?",
                "options": ["yes", "no"],
            },
        }


class _RetrieveProvider:
    def inspect(self, **_kwargs):
        return {
            "schema_version": 2,
            "status": "RETRIEVE_MORE",
            "evidence_gaps": [
                {
                    "code": "MISSING_CURRENT_STATE",
                    "description": "need current task state",
                    "required_information": ["current task status"],
                }
            ],
        }


def _intent():
    return {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
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
        "meta": {"artifact_id": "retrieval-1", "revision": 3, "based_on": []},
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


def _plan():
    return {
        "schema_version": 2,
        "meta": {
            "artifact_id": "plan-1",
            "revision": 2,
            "based_on": [
                {"artifact_id": "route-output-1", "revision": 1},
                {"artifact_id": "analysis-1", "revision": 4},
                {"artifact_id": "retrieval-1", "revision": 3},
            ],
        },
        "actions": [
            {
                "action_id": "action-1",
                "route_id": "route-1",
                "tool_id": "tasks_update_task",
                "effect": "UPDATE",
                "arguments": {"task_id": "task-1", "task_list_id": "list-1"},
                "evidence_refs": ["ev-1"],
                "depends_on_action_ids": [],
            }
        ],
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


def test_review_meta_binds_exact_current_planning_revision() -> None:
    producer = ReviewV2Producer(
        candidate_provider=_PassProvider(),
        artifact_id_factory=lambda: "review-1",
    )
    result = producer.run(
        request_intent=_intent(),
        retrieval_result=_retrieval(),
        work_analysis_result=_analysis(),
        planning_result=_plan(),
        evidence_drafts=_evidence(),
    )
    assert result["disposition"] == "PASS"
    assert result["workflow_signal"] is None
    assert result["typed_result"]["meta"]["based_on"] == [{"artifact_id": "plan-1", "revision": 2}]


def test_review_confirmation_keeps_application_owned_resume_identity() -> None:
    producer = ReviewV2Producer(
        candidate_provider=_ConfirmProvider(),
        artifact_id_factory=lambda: "review-1",
    )
    result = producer.run(
        request_intent=_intent(),
        retrieval_result=_retrieval(),
        work_analysis_result=_analysis(),
        planning_result=_plan(),
        evidence_drafts=_evidence(),
        interrupt_id="interrupt-1",
        resume_target=AgentNodeResumeTargetV2(
            kind="AGENT_NODE",
            semantic_owner_id="REVIEW",
            compiled_subgraph_id="SIX_REVIEW",
            node_id="review.aggregate_findings",
            graph_profile="SIX_ROLE_BASELINE",
            graph_version="runtime-v2",
        ),
    )
    assert result["disposition"] == "CONFIRM"
    assert result["typed_result"]["status"] == "CONFIRM"
    assert result["workflow_signal"]["kind"] == "CONFIRMATION_REQUIRED"
    assert result["workflow_signal"]["semantic_owner_id"] == "REVIEW"
    assert result["workflow_signal"]["interrupt_id"] == "interrupt-1"


def test_review_retrieve_more_can_deterministically_reconsider_route() -> None:
    producer = ReviewV2Producer(
        candidate_provider=_RetrieveProvider(),
        artifact_id_factory=lambda: "review-1",
        retrieval_need_satisfier=lambda _needs: False,
    )
    result = producer.run(
        request_intent=_intent(),
        retrieval_result=_retrieval(),
        work_analysis_result=_analysis(),
        planning_result=_plan(),
        evidence_drafts=_evidence(),
    )
    assert result["disposition"] == "RETRIEVE_MORE"
    assert result["workflow_signal"] == {
        "kind": "ROUTE_RECONSIDERATION_REQUIRED",
        "reason_codes": ["MISSING_CURRENT_STATE"],
    }


def test_stale_planning_result_is_rejected_before_review_candidate() -> None:
    stale = _plan()
    stale["meta"] = {
        "artifact_id": "plan-1",
        "revision": 2,
        "based_on": [
            {"artifact_id": "analysis-1", "revision": 3},
            {"artifact_id": "retrieval-1", "revision": 3},
        ],
    }
    producer = ReviewV2Producer(
        candidate_provider=_PassProvider(),
        artifact_id_factory=lambda: "review-1",
    )
    with pytest.raises(ReviewV2RuntimeError, match="stale PlanningResultV2"):
        producer.run(
            request_intent=_intent(),
            retrieval_result=_retrieval(),
            work_analysis_result=_analysis(),
            planning_result=stale,
            evidence_drafts=_evidence(),
        )
