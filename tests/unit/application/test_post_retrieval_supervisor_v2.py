from __future__ import annotations

from dataclasses import dataclass

import pytest
from evaluation.compat.post_retrieval_envelopes import PlanningResultV2
from evaluation.compat.supervise_post_retrieval import (
    RevisionBudgetBlockBoundaryRequired,
    RevisionBudgetBlockContextV1,
    route_planning_return_v2,
    route_review_return_v2,
    route_work_analysis_return_v2,
)

from google_work_agent.application.agents.state_artifact import StateArtifactMetaV1
from google_work_agent.application.use_cases.run.block_run import BlockRunCommand
from google_work_agent.application.use_cases.run.guard_run_budget import (
    approve_semantic_revision,
    build_default_run_budget,
    build_semantic_failure_signature_v1,
)
from google_work_agent.ports.system.contracts.workflow_signal import SubgraphReturnV2


def _meta(name: str) -> StateArtifactMetaV1:
    return {"artifact_id": name, "revision": 1, "based_on": []}


def _plan() -> PlanningResultV2:
    return {
        "schema_version": 2,
        "meta": _meta("plan-1"),
        "actions": [
            {
                "action_id": "a1",
                "route_id": "r1",
                "tool_id": "tasks_create_task",
                "effect": "CREATE",
                "arguments": {"task_list_id": "l1", "payload": {"title": "x"}},
                "evidence_refs": ["ev-1"],
                "depends_on_action_ids": [],
            }
        ],
    }


def _revise_return() -> SubgraphReturnV2[object]:
    return {
        "disposition": "REVISE",
        "typed_result": {
            "schema_version": 2,
            "meta": _meta("review-1"),
            "status": "REVISE",
            "issues": [
                {
                    "code": "PLAN_WRONG_TARGET",
                    "description": "wrong",
                    "affected_dimensions": ["review.inspect_action_scope_and_route"],
                    "affected_action_ids": ["a1"],
                    "affected_route_ids": ["r1"],
                    "evidence_refs": ["ev-1"],
                }
            ],
        },
        "workflow_signal": None,
    }


def _block_context() -> RevisionBudgetBlockContextV1:
    return {
        "command_id": "command-1",
        "request_hash": "hash-1",
        "run_id": "run-1",
        "expected_version": 7,
    }


@dataclass
class _BlockResponse:
    applied: bool
    run_status: str = "BLOCKED"


class _BlockRun:
    def __init__(self, *, applied: bool) -> None:
        self.applied = applied
        self.commands: list[BlockRunCommand] = []

    def __call__(self, command: object) -> _BlockResponse:
        assert isinstance(command, BlockRunCommand)
        self.commands.append(command)
        return _BlockResponse(applied=self.applied)


def test_planning_answer_only_skips_review() -> None:
    decision = route_planning_return_v2(
        {
            "disposition": "ANSWER_ONLY",
            "typed_result": {
                "schema_version": 2,
                "meta": _meta("answer-1"),
                "answer": "done",
                "evidence_refs": [],
            },
            "workflow_signal": None,
        }
    )
    assert decision["target"] == "RESPONSE_SYNTHESIS"


def test_analysis_needs_more_data_uses_signal_not_result_internals() -> None:
    decision = route_work_analysis_return_v2(
        {
            "disposition": "NEEDS_MORE_DATA",
            "typed_result": None,
            "workflow_signal": {
                "kind": "RETRIEVAL_REQUIRED",
                "reason_codes": ["MISSING_RECIPIENT"],
                "needs": [
                    {
                        "required_information": "recipient email",
                        "reason_codes": ["MISSING_RECIPIENT"],
                    }
                ],
            },
        }
    )
    assert decision["target"] == "RETRIEVAL"
    assert decision["reason_code"] == "MISSING_RECIPIENT"


def test_review_pass_routes_action_plan_to_domain_validation() -> None:
    decision = route_review_return_v2(
        {
            "disposition": "PASS",
            "typed_result": {
                "schema_version": 2,
                "meta": _meta("review-1"),
                "status": "PASS",
                "summary": "ok",
            },
            "workflow_signal": None,
        },
        planning_result=_plan(),
        retry_budget=build_default_run_budget(),
    )
    assert decision["target"] == "DOMAIN_VALIDATION"


def test_review_revise_uses_canonical_issue_code_for_semantic_budget() -> None:
    decision = route_review_return_v2(
        _revise_return(), planning_result=_plan(), retry_budget=build_default_run_budget()
    )
    assert decision["target"] == "PLANNING"
    assert decision["revision_mode"] == "PLAN"
    assert decision["retry_budget"] is not None


def test_planning_revision_budget_deny_blocks_run_then_finalizes_when_applied() -> None:
    budget = build_default_run_budget()
    budget["planning_revisions_used"] = 2
    block_run = _BlockRun(applied=True)
    decision = route_review_return_v2(
        _revise_return(),
        planning_result=_plan(),
        retry_budget=budget,
        block_run=block_run,
        budget_block_context=_block_context(),
    )
    assert decision["target"] == "FINALIZE"
    assert decision["reason_code"] == "PLANNING_REVISION_BUDGET_EXHAUSTED"
    assert len(block_run.commands) == 1
    assert block_run.commands[0].reason_code == "PLANNING_REVISION_BUDGET_EXHAUSTED"


def test_semantic_revision_budget_deny_blocks_run_then_finalizes_when_applied() -> None:
    budget = build_default_run_budget()
    budget = approve_semantic_revision(
        budget,
        signature=build_semantic_failure_signature_v1(
            node_id="planning.revise_plan", failure_reason_codes=["PLAN_WRONG_TARGET"]
        ),
    )["run_budget"]
    block_run = _BlockRun(applied=True)
    decision = route_review_return_v2(
        _revise_return(),
        planning_result=_plan(),
        retry_budget=budget,
        block_run=block_run,
        budget_block_context=_block_context(),
    )
    assert decision["target"] == "FINALIZE"
    assert decision["reason_code"] == "SEMANTIC_REVISION_BUDGET_EXHAUSTED"
    assert block_run.commands[0].reason_code == "SEMANTIC_REVISION_BUDGET_EXHAUSTED"


@pytest.mark.parametrize("semantic", [False, True])
def test_revision_budget_block_applied_false_routes_domain_reconciliation(semantic: bool) -> None:
    budget = build_default_run_budget()
    if semantic:
        budget = approve_semantic_revision(
            budget,
            signature=build_semantic_failure_signature_v1(
                node_id="planning.revise_plan", failure_reason_codes=["PLAN_WRONG_TARGET"]
            ),
        )["run_budget"]
    else:
        budget["planning_revisions_used"] = 2
    decision = route_review_return_v2(
        _revise_return(),
        planning_result=_plan(),
        retry_budget=budget,
        block_run=_BlockRun(applied=False),
        budget_block_context=_block_context(),
    )
    assert decision["target"] == "DOMAIN_RECONCILE"
    assert decision["reason_code"] in {
        "PLANNING_REVISION_BUDGET_EXHAUSTED",
        "SEMANTIC_REVISION_BUDGET_EXHAUSTED",
    }


def test_revision_budget_deny_requires_blockrun_boundary_not_guessed_edge() -> None:
    budget = build_default_run_budget()
    budget["planning_revisions_used"] = 2
    with pytest.raises(RevisionBudgetBlockBoundaryRequired):
        route_review_return_v2(_revise_return(), planning_result=_plan(), retry_budget=budget)
