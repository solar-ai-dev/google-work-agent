"""Pure canonical routing for Work Analysis, Planning, and Review V2 returns.

The router consumes only validated ``SubgraphReturnV2`` envelopes. Unknown
versions/dispositions and impossible artifact combinations fail closed to
RECOVERY/CONTRACT_VIOLATION. Revision-budget exhaustion is a Domain transition,
not a contract violation: the Application BlockRun boundary is invoked before
FINALIZE and DOMAIN_RECONCILE is selected when durable state does not match the
checkpoint projection.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, Protocol, TypedDict, cast

from google_work_agent.application.workflows.contracts import (
    BudgetDecision,
    BudgetDecisionV1,
    RunBudgetV1,
    approve_planning_revision,
    approve_semantic_revision,
    build_semantic_failure_signature_v1,
)
from google_work_agent.application.workflows.handoff_contracts import SubgraphReturnV2
from google_work_agent.application.workflows.post_retrieval_envelopes_v2 import (
    PlanningResultV2,
    validate_planning_return_v2,
    validate_review_return_v2,
    validate_work_analysis_return_v2,
)

PostRetrievalTargetV2 = Literal[
    "TOOL_ROUTE",
    "RETRIEVAL",
    "PLANNING",
    "REVIEW",
    "DOMAIN_VALIDATION",
    "RESPONSE_SYNTHESIS",
    "WAITING_CONFIRMATION",
    "BLOCK_RUN",
    "DOMAIN_RECONCILE",
    "RECOVERY",
    "FINALIZE",
]
RevisionModeV2 = Literal["ANSWER", "PLAN"]


class PostRetrievalRouteDecisionV2(TypedDict):
    target: PostRetrievalTargetV2
    reason_code: str
    retry_budget: RunBudgetV1 | None
    budget_decision: BudgetDecisionV1 | None
    revision_mode: RevisionModeV2 | None


class RevisionBudgetBlockContextV1(TypedDict):
    command_id: str
    request_hash: str
    run_id: str
    expected_version: int


class BlockRunResult(Protocol):
    applied: bool
    run_status: str


BlockRunExecutor = Callable[[object], BlockRunResult]


class RevisionBudgetBlockBoundaryRequired(RuntimeError):
    """Raised when routing cannot invoke the required Application BlockRun boundary."""


def route_work_analysis_return_v2(value: object) -> PostRetrievalRouteDecisionV2:
    try:
        envelope = validate_work_analysis_return_v2(value)
    except ValueError:
        return _contract_violation()
    disposition = envelope["disposition"]
    if disposition == "COMPLETE":
        return _decision("PLANNING", "WORK_ANALYSIS_COMPLETE")
    if disposition == "NEEDS_MORE_DATA":
        signal_kind = _signal_kind(envelope)
        if signal_kind == "RETRIEVAL_REQUIRED":
            return _decision(
                "RETRIEVAL",
                _first_signal_reason(envelope, "WORK_ANALYSIS_NEEDS_MORE_DATA"),
            )
        return _decision(
            "TOOL_ROUTE",
            _first_signal_reason(envelope, "WORK_ANALYSIS_ROUTE_REQUIRED"),
        )
    if disposition == "NEEDS_CONFIRMATION":
        return _decision("WAITING_CONFIRMATION", "WORK_ANALYSIS_NEEDS_CONFIRMATION")
    if disposition == "ROUTE_RECONSIDERATION_REQUIRED":
        return _decision("TOOL_ROUTE", _first_signal_reason(envelope, disposition))
    return _decision("BLOCK_RUN", _first_signal_reason(envelope, "WORK_ANALYSIS_BLOCKED"))


def route_planning_return_v2(value: object) -> PostRetrievalRouteDecisionV2:
    try:
        envelope = validate_planning_return_v2(value)
    except ValueError:
        return _contract_violation()
    disposition = envelope["disposition"]
    if disposition == "ANSWER_ONLY":
        return _decision("RESPONSE_SYNTHESIS", "PLANNING_ANSWER_ONLY")
    if disposition == "PLAN_READY":
        return _decision("REVIEW", "PLANNING_PLAN_READY")
    if disposition == "NEEDS_CONFIRMATION":
        return _decision("WAITING_CONFIRMATION", "PLANNING_NEEDS_CONFIRMATION")
    if disposition == "ROUTE_RECONSIDERATION_REQUIRED":
        return _decision("TOOL_ROUTE", _first_signal_reason(envelope, disposition))
    return _decision("BLOCK_RUN", _first_signal_reason(envelope, "PLANNING_BLOCKED"))


def route_review_return_v2(
    value: object,
    *,
    planning_result: PlanningResultV2,
    retry_budget: RunBudgetV1,
    block_run: BlockRunExecutor | None = None,
    budget_block_context: RevisionBudgetBlockContextV1 | None = None,
) -> PostRetrievalRouteDecisionV2:
    try:
        envelope = validate_review_return_v2(value)
    except ValueError:
        return _contract_violation()
    disposition = envelope["disposition"]
    if disposition == "PASS":
        if isinstance(planning_result, dict) and "answer" in planning_result:
            return _contract_violation()
        return _decision("DOMAIN_VALIDATION", "PLAN_REVIEW_PASS")
    if disposition == "REVISE":
        return _route_review_revise(
            envelope,
            planning_result=planning_result,
            retry_budget=retry_budget,
            block_run=block_run,
            budget_block_context=budget_block_context,
        )
    if disposition == "RETRIEVE_MORE":
        if _signal_kind(envelope) == "RETRIEVAL_REQUIRED":
            return _decision(
                "RETRIEVAL",
                _first_signal_reason(envelope, "PLAN_REVIEW_RETRIEVE_MORE"),
            )
        return _decision(
            "TOOL_ROUTE",
            _first_signal_reason(envelope, "PLAN_REVIEW_ROUTE_REQUIRED"),
        )
    if disposition == "ROUTE_RECONSIDERATION":
        return _decision("TOOL_ROUTE", _first_signal_reason(envelope, disposition))
    if disposition == "CONFIRM":
        return _decision("WAITING_CONFIRMATION", "PLAN_REVIEW_CONFIRM")
    return _decision("BLOCK_RUN", _first_signal_reason(envelope, "PLAN_REVIEW_BLOCK"))


def _route_review_revise(
    envelope: SubgraphReturnV2[object],
    *,
    planning_result: PlanningResultV2,
    retry_budget: RunBudgetV1,
    block_run: BlockRunExecutor | None,
    budget_block_context: RevisionBudgetBlockContextV1 | None,
) -> PostRetrievalRouteDecisionV2:
    revision = approve_planning_revision(retry_budget)
    if revision["decision"] == BudgetDecision.DENY.value:
        return _route_revision_budget_deny(
            decision=revision,
            reason_code="PLANNING_REVISION_BUDGET_EXHAUSTED",
            block_run=block_run,
            context=budget_block_context,
        )

    review = cast(dict[str, object], envelope["typed_result"])
    raw_issues = review.get("issues")
    issue_codes = [
        cast(str, issue["code"])
        for issue in cast(list[dict[str, object]], raw_issues)
        if isinstance(issue.get("code"), str) and issue["code"]
    ]
    revision_mode: RevisionModeV2 = (
        "ANSWER" if isinstance(planning_result, dict) and "answer" in planning_result else "PLAN"
    )
    if issue_codes:
        signature = build_semantic_failure_signature_v1(
            node_id=(
                "planning.revise_answer" if revision_mode == "ANSWER" else "planning.revise_plan"
            ),
            failure_reason_codes=issue_codes,
        )
        semantic = approve_semantic_revision(revision["run_budget"], signature=signature)
        if semantic["decision"] == BudgetDecision.DENY.value:
            return _route_revision_budget_deny(
                decision=semantic,
                reason_code="SEMANTIC_REVISION_BUDGET_EXHAUSTED",
                block_run=block_run,
                context=budget_block_context,
            )
        return _decision(
            "PLANNING",
            "PLAN_REVIEW_REVISE",
            retry_budget=semantic["run_budget"],
            budget_decision=semantic,
            revision_mode=revision_mode,
        )
    return _decision(
        "PLANNING",
        "PLAN_REVIEW_REVISE",
        retry_budget=revision["run_budget"],
        budget_decision=revision,
        revision_mode=revision_mode,
    )


def _route_revision_budget_deny(
    *,
    decision: BudgetDecisionV1,
    reason_code: Literal[
        "PLANNING_REVISION_BUDGET_EXHAUSTED",
        "SEMANTIC_REVISION_BUDGET_EXHAUSTED",
    ],
    block_run: BlockRunExecutor | None,
    context: RevisionBudgetBlockContextV1 | None,
) -> PostRetrievalRouteDecisionV2:
    if block_run is None or context is None:
        raise RevisionBudgetBlockBoundaryRequired(
            f"{reason_code} requires injected Application BlockRun boundary and command context"
        )
    from google_work_agent.application.run_terminal import BlockRunCommand

    response = block_run(
        BlockRunCommand(
            command_id=context["command_id"],
            request_hash=context["request_hash"],
            run_id=context["run_id"],
            expected_version=context["expected_version"],
            reason_code=reason_code,
        )
    )
    if response.applied:
        return _decision(
            "FINALIZE",
            reason_code,
            retry_budget=decision["run_budget"],
            budget_decision=decision,
        )
    return _decision(
        "DOMAIN_RECONCILE",
        reason_code,
        retry_budget=decision["run_budget"],
        budget_decision=decision,
    )


def _signal_kind(envelope: SubgraphReturnV2[object]) -> str:
    signal = envelope["workflow_signal"]
    if not isinstance(signal, dict) or not isinstance(signal.get("kind"), str):
        raise ValueError("validated envelope lost workflow_signal kind")
    return cast(str, signal["kind"])


def _first_signal_reason(envelope: SubgraphReturnV2[object], default: str) -> str:
    signal = envelope["workflow_signal"]
    if not isinstance(signal, dict):
        return default
    reasons = signal.get("reason_codes")
    if isinstance(reasons, list):
        for reason in reasons:
            if isinstance(reason, str) and reason:
                return reason
    return default


def _contract_violation() -> PostRetrievalRouteDecisionV2:
    return _decision("RECOVERY", "CONTRACT_VIOLATION")


def _decision(
    target: PostRetrievalTargetV2,
    reason_code: str,
    *,
    retry_budget: RunBudgetV1 | None = None,
    budget_decision: BudgetDecisionV1 | None = None,
    revision_mode: RevisionModeV2 | None = None,
) -> PostRetrievalRouteDecisionV2:
    return {
        "target": target,
        "reason_code": reason_code,
        "retry_budget": retry_budget,
        "budget_decision": budget_decision,
        "revision_mode": revision_mode,
    }


__all__ = [
    "BlockRunExecutor",
    "PostRetrievalRouteDecisionV2",
    "PostRetrievalTargetV2",
    "RevisionBudgetBlockBoundaryRequired",
    "RevisionBudgetBlockContextV1",
    "RevisionModeV2",
    "route_planning_return_v2",
    "route_review_return_v2",
    "route_work_analysis_return_v2",
]
