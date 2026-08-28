"""Action-owner-local lifecycle projections over repository CAS methods."""

from google_work_agent.domain.action.model import Action, ActionStatusV1, canonicalize_action_risk
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.execution_attempt.model import (
    ExecutionAttempt,
    ExecutionAttemptStatusV1,
)
from google_work_agent.domain.plan.model import Plan, PlanStatusV1
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


def update_action_record(
    unit_of_work: UnitOfWork,
    action_id: str,
    *,
    expected_version: int,
    expected_status: ActionStatusV1,
    next_status: ActionStatusV1,
    updated_at_ms: int,
    arguments_json: str | None = None,
    arguments_hash: str | None = None,
    risk: dict[str, object] | None = None,
) -> Action | None:
    values: dict[str, object] = {
        "status": next_status,
        "updated_at_ms": updated_at_ms,
    }
    if next_status is not expected_status or arguments_json is not None:
        values["version"] = expected_version + 1
    if arguments_json is not None:
        values["arguments_json"] = arguments_json
    if arguments_hash is not None:
        values["arguments_hash"] = arguments_hash
    if risk is not None:
        values["risk_json"] = canonicalize_action_risk(risk)
    applied = unit_of_work.actions.update_if_version_and_status(
        action_id,
        expected_version,
        frozenset({expected_status}),
        values,
    )
    return unit_of_work.actions.get(action_id) if applied else None


def update_plan_record(
    unit_of_work: UnitOfWork,
    plan_id: str,
    *,
    expected_status: PlanStatusV1,
    next_status: PlanStatusV1,
) -> Plan | None:
    current = unit_of_work.plans.load_bundle(plan_id)
    if current is None:
        return None
    applied = unit_of_work.plans.update_if_version_and_status(
        plan_id,
        current.revision_no,
        frozenset({expected_status}),
        {"status": next_status},
    )
    return unit_of_work.plans.load_bundle(plan_id) if applied else None


def update_approval_status(
    unit_of_work: UnitOfWork,
    approval_id: str,
    *,
    expected_status: ApprovalStatusV1,
    next_status: ApprovalStatusV1,
    consumed_at_ms: int | None = None,
) -> bool:
    values: dict[str, object] = {"status": next_status}
    if consumed_at_ms is not None:
        values["consumed_at_ms"] = consumed_at_ms
    return unit_of_work.approvals.update_if_status(
        approval_id,
        expected_status,
        values,
    )


def update_execution_attempt_record(
    unit_of_work: UnitOfWork,
    attempt_id: str,
    *,
    expected_version: int,
    expected_status: ExecutionAttemptStatusV1,
    status: ExecutionAttemptStatusV1,
    error_code: str | None,
    error_detail_json: str | None,
    result_resource_ref_id: str | None,
    response_metadata_json: str | None,
    finished_at_ms: int | None,
) -> ExecutionAttempt | None:
    applied = unit_of_work.execution_attempts.update_if_version_and_status(
        attempt_id,
        expected_version,
        frozenset({expected_status}),
        {
            "status": status,
            "version": expected_version + 1,
            "error_code": error_code,
            "error_detail_json": error_detail_json,
            "result_resource_ref_id": result_resource_ref_id,
            "response_metadata_json": response_metadata_json,
            "finished_at_ms": finished_at_ms,
        },
    )
    return unit_of_work.execution_attempts.get(attempt_id) if applied else None
