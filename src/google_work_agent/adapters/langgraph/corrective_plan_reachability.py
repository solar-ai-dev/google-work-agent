"""Production reachability guard for failure-safe corrective-plan continuation."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from google_work_agent.adapters.langgraph.corrective_plan_persistence import (
    _build_durable_materialization_proof,
    persist_reserved_corrective_write_plan,
)
from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.adapters.langgraph.main.validate_planning_output import (
    RunScopedResourceIdentityReader,
)
from google_work_agent.application.agents.planning.contracts.action_plan_draft import (
    ActionPlanDraftV2,
)
from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.model import RunStatusV1


class CorrectivePlanContinuationRequired(RuntimeError):
    """A verified Save-only corrective revision needs a later Publish continuation."""

    def __init__(self, *, run_id: str, plan_id: str, cause: Exception) -> None:
        super().__init__(str(cause))
        self.run_id = run_id
        self.plan_id = plan_id


class _FailureDisposition(StrEnum):
    UNSAFE = "UNSAFE"
    CONTINUATION_REQUIRED = "CONTINUATION_REQUIRED"
    ALREADY_PUBLISHED = "ALREADY_PUBLISHED"


def persist_reachable_corrective_write_plan(
    runtime: Any,
    *,
    state: GraphState,
    plan: ActionPlanDraftV2,
    resource_identity_reader: RunScopedResourceIdentityReader,
    reserved_plan: PlanRecord,
) -> str:
    """Persist corrective work while preserving a production-reachable retry seam.

    The persistence helper owns both initial transient materialization and
    durable restart continuation. If it raises, only a proof reconstructed from
    the committed aggregate and command receipts may reclassify the failure.
    """

    try:
        return persist_reserved_corrective_write_plan(
            runtime,
            state=state,
            plan=plan,
            resource_identity_reader=resource_identity_reader,
            reserved_plan=reserved_plan,
        )
    except Exception as error:
        disposition = _classify_failure_after_corrective_save(
            runtime,
            state=state,
            plan=plan,
            reserved_plan=reserved_plan,
        )
        if disposition is _FailureDisposition.ALREADY_PUBLISHED:
            return reserved_plan.id
        if disposition is _FailureDisposition.CONTINUATION_REQUIRED:
            raise CorrectivePlanContinuationRequired(
                run_id=reserved_plan.run_id,
                plan_id=reserved_plan.id,
                cause=error,
            ) from error
        raise


def _classify_failure_after_corrective_save(
    runtime: Any,
    *,
    state: GraphState,
    plan: ActionPlanDraftV2,
    reserved_plan: PlanRecord,
) -> _FailureDisposition:
    """Classify only states proven from durable Save/Plan/child facts."""

    try:
        proof = _build_durable_materialization_proof(
            runtime,
            state=state,
            plan=plan,
            reserved_plan=reserved_plan,
        )
    except Exception:
        return _FailureDisposition.UNSAFE

    if (
        proof["run_status"] is RunStatusV1.PLANNING
        and proof["plan_status"] is PlanStatusV1.DRAFT
        and proof["publish_receipt_present"] is False
    ):
        return _FailureDisposition.CONTINUATION_REQUIRED

    if (
        proof["run_status"] is RunStatusV1.WAITING_APPROVAL
        and proof["plan_status"] is PlanStatusV1.WAITING_APPROVAL
    ):
        return _FailureDisposition.ALREADY_PUBLISHED

    return _FailureDisposition.UNSAFE


__all__ = [
    "CorrectivePlanContinuationRequired",
    "persist_reachable_corrective_write_plan",
]
