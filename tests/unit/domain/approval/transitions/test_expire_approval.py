import pytest

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.approval.guards.expire_approval import ApprovalExpiryInput
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.approval.transitions.expire_approval import (
    transition_expire_approval,
)
from google_work_agent.domain.plan.model import PlanStatusV1


def _input(**changes: object) -> ApprovalExpiryInput:
    values: dict[str, object] = {
        "action_status": ActionStatusV1.APPROVED,
        "action_version": 3,
        "current_arguments_hash": "arguments",
        "approval_status": ApprovalStatusV1.ACTIVE,
        "approval_action_version": 3,
        "approval_arguments_hash": "arguments",
        "approval_source_snapshot_hash": "source",
        "current_source_snapshot_hash": "source",
        "approval_policy_version": "policy",
        "current_policy_version": "policy",
        "approval_tool_schema_version": "schema",
        "current_tool_schema_version": "schema",
        "expires_at_ms": 101,
        "now_ms": 100,
        "plan_status": PlanStatusV1.WAITING_APPROVAL,
        "plan_is_current": True,
    }
    values.update(changes)
    return ApprovalExpiryInput(**values)  # type: ignore[arg-type]


def test_expire_approval_is_a_coupled_mutation() -> None:
    assert transition_expire_approval(_input(now_ms=101)) == (
        ActionStatusV1.EXPIRED,
        ApprovalStatusV1.EXPIRED,
    )


@pytest.mark.parametrize(
    "plan_status",
    [status for status in PlanStatusV1 if status is not PlanStatusV1.WAITING_APPROVAL],
)
def test_expire_approval_rejects_non_waiting_plan(plan_status: PlanStatusV1) -> None:
    with pytest.raises(ValueError):
        transition_expire_approval(_input(plan_status=plan_status, now_ms=101))


def test_expire_approval_rejects_still_current_active_approval() -> None:
    with pytest.raises(ValueError, match="still-current"):
        transition_expire_approval(_input())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("approval_action_version", 2),
        ("approval_arguments_hash", "old-arguments"),
        ("approval_source_snapshot_hash", "old-source"),
        ("approval_policy_version", "old-policy"),
        ("approval_tool_schema_version", "old-schema"),
    ],
)
def test_expire_approval_accepts_each_canonical_stale_binding(field: str, value: object) -> None:
    assert transition_expire_approval(_input(**{field: value}))[0] is ActionStatusV1.EXPIRED
