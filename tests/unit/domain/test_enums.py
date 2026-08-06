from google_work_agent.domain import (
    ActionStatus,
    ApprovalRequirement,
    ApprovalStatus,
    EffectType,
    ExecutionAttemptStatus,
    RecoveryPolicy,
    ResultCode,
    RunStatus,
    VerificationPolicy,
    VerificationStatus,
)


def test_run_status_values_match_sql() -> None:
    assert tuple(status.value for status in RunStatus) == (
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


def test_action_status_values_match_sql() -> None:
    assert tuple(status.value for status in ActionStatus) == (
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
    )


def test_other_enum_values_match_contract() -> None:
    assert tuple(status.value for status in ApprovalStatus) == (
        "ACTIVE",
        "EXPIRED",
        "CONSUMED",
        "REVOKED",
    )
    assert tuple(requirement.value for requirement in ApprovalRequirement) == ("NONE", "REQUIRED")
    assert tuple(status.value for status in ExecutionAttemptStatus) == (
        "CLAIMED",
        "EXECUTING",
        "UNKNOWN_RESULT",
        "SUCCEEDED",
        "FAILED",
    )
    assert tuple(status.value for status in VerificationStatus) == (
        "VERIFIED",
        "MISMATCH",
        "NOT_FOUND",
        "ERROR",
    )
    assert tuple(policy.value for policy in VerificationPolicy) == ("NONE", "GET_COMPARE")
    assert tuple(policy.value for policy in RecoveryPolicy) == (
        "NONE",
        "GET_TARGET",
        "RESOURCE_SEARCH",
    )
    assert tuple(effect.value for effect in EffectType) == ("READ", "CREATE", "UPDATE")
    assert tuple(code.value for code in ResultCode) == (
        "TRANSITION_APPLIED",
        "STATE_CONFLICT",
        "VERSION_CONFLICT",
        "DUPLICATE_COMMAND",
    )


def test_effect_type_has_no_delete() -> None:
    assert "DELETE" not in {effect.value for effect in EffectType}


def test_status_values_are_unique() -> None:
    for enum_type in (RunStatus, ActionStatus):
        values = [status.value for status in enum_type]
        assert len(values) == len(set(values))
