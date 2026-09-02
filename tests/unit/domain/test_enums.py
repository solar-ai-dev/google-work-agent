from google_work_agent.domain.action.model import (
    ActionStatusV1,
    ApprovalRequirement,
    EffectType,
    RecoveryPolicy,
    VerificationPolicy,
)
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.domain.verification.model import VerificationStatus


def test_run_status__values_match__sql() -> None:
    assert tuple(status.value for status in RunStatusV1) == (
        "CREATED",
        "ANALYZING",
        "RETRIEVING",
        "WAITING_CONFIRMATION",
        "PLANNING",
        "WAITING_APPROVAL",
        "EXECUTING",
        "VERIFYING",
        "COMPLETED",
        "CANCEL_REQUESTED",
        "CANCELLED",
        "REAUTH_REQUIRED",
        "RECOVERY_REQUIRED",
        "FAILED",
        "BLOCKED",
    )


def test_action_status__values_match__sql() -> None:
    assert tuple(status.value for status in ActionStatusV1) == (
        "PROPOSED",
        "MODIFIED",
        "APPROVED",
        "REJECTED",
        "EXPIRED",
        "EXECUTING",
        "UNKNOWN_RESULT",
        "EXECUTED",
        "VERIFIED",
        "FAILED",
        "BLOCKED",
        "DEPENDENCY_BLOCKED",
        "MISMATCH",
        "CANCELLED",
    )


def test_other_enum__values_match__contract() -> None:
    assert tuple(status.value for status in ApprovalStatusV1) == (
        "ACTIVE",
        "EXPIRED",
        "CONSUMED",
        "REVOKED",
    )
    assert tuple(requirement.value for requirement in ApprovalRequirement) == ("NONE", "REQUIRED")
    assert tuple(status.value for status in ExecutionAttemptStatusV1) == (
        "CLAIMED",
        "EXECUTING",
        "UNKNOWN_RESULT",
        "SUCCEEDED",
        "FAILED",
    )
    assert tuple(status.value for status in VerificationStatus) == (
        "VERIFIED",
        "MISMATCH",
    )
    assert tuple(policy.value for policy in VerificationPolicy) == (
        "NONE",
        "GET_COMPARE",
        "SENT_LOOKUP",
        "GET_ABSENT",
    )
    assert tuple(policy.value for policy in RecoveryPolicy) == (
        "NONE",
        "GET_TARGET",
        "RESOURCE_SEARCH",
        "MESSAGE_SEARCH",
    )
    assert tuple(effect.value for effect in EffectType) == (
        "READ",
        "CREATE",
        "UPDATE",
        "SEND",
        "DELETE",
    )
    assert tuple(code.value for code in ResultCode) == (
        "TRANSITION_APPLIED",
        "STATE_CONFLICT",
        "VERSION_CONFLICT",
        "DUPLICATE_COMMAND",
        "RECOVERY_REQUIRED",
        "SCHEMA_VIOLATION",
        "NO_PROGRESS",
        "RESOLUTION_NOT_ALLOWED",
    )


def test_effect_type__includes_send__and_delete() -> None:
    assert {"SEND", "DELETE"} <= {effect.value for effect in EffectType}


def test_status_values__are__unique() -> None:
    for enum_type in (RunStatusV1, ActionStatusV1):
        values = [status.value for status in enum_type]
        assert len(values) == len(set(values))
