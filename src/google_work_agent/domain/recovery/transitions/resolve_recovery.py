"""Canonical reason-aware Recovery resolution transition."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.domain.action.model import ActionStatus
from google_work_agent.domain.recovery.guards.resolve_recovery import guard_resolve_recovery
from google_work_agent.domain.recovery.model import RecoveryReasonV1, RecoveryResolution
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatus, RunTransitionRejected


@dataclass(frozen=True, slots=True)
class RecoveryResolutionDecision:
    applied: bool
    result_code: ResultCode
    current_status: RunStatus
    conflict_detail: str | None = None


def transition_resolve_recovery(
    current_status: RunStatus,
    *,
    resolution: RecoveryResolution,
    reason: RecoveryReasonV1,
    pre_recovery_status: RunStatus,
    recheck_input_changed: bool = False,
    recovered_action_status: ActionStatus | None = None,
    validated_resume_status: RunStatus | None = None,
    cancel_intent_active: bool = False,
    unresolved_external_effect_count: int = 0,
    irrecoverable_confirmed: bool = False,
) -> RecoveryResolutionDecision:
    """Apply only a resolution permitted by the durable RecoveryContext facts.

    The Application layer supplies these values from ``RecoveryContextV1`` and
    the recheck lookup.  This pure transition owns their legality and never
    treats a same-input recheck as an applied transition.
    """
    try:
        guard_resolve_recovery(current_status)
    except RunTransitionRejected as error:
        return _reject(ResultCode.STATE_CONFLICT, current_status, str(error))

    if resolution is RecoveryResolution.RECHECK:
        return _resolve_recheck(
            reason=reason,
            pre_recovery_status=pre_recovery_status,
            recheck_input_changed=recheck_input_changed,
            recovered_action_status=recovered_action_status,
            validated_resume_status=validated_resume_status,
        )

    if resolution in {
        RecoveryResolution.ACCEPT_PARTIAL,
        RecoveryResolution.CREATE_CORRECTIVE_PLAN,
    }:
        if reason != "VERIFICATION_MISMATCH":
            return _reject(
                ResultCode.RESOLUTION_NOT_ALLOWED,
                current_status,
                f"{resolution.value} is only allowed for VERIFICATION_MISMATCH",
            )
        if cancel_intent_active:
            return _reject(
                ResultCode.RESOLUTION_NOT_ALLOWED,
                current_status,
                f"{resolution.value} is forbidden while cancel intent is active",
            )
        return _applied(
            RunStatus.COMPLETED
            if resolution is RecoveryResolution.ACCEPT_PARTIAL
            else RunStatus.PLANNING
        )

    if resolution is RecoveryResolution.CANCEL:
        if not cancel_intent_active or unresolved_external_effect_count:
            return _reject(
                ResultCode.RESOLUTION_NOT_ALLOWED,
                current_status,
                "CANCEL requires durable cancel intent and no unresolved external effect",
            )
        if reason == "UNKNOWN_RESULT" and recovered_action_status not in {
            ActionStatus.EXECUTED,
            ActionStatus.FAILED,
        }:
            return _reject(
                ResultCode.RESOLUTION_NOT_ALLOWED,
                current_status,
                "UNKNOWN_RESULT must be settled before CANCEL",
            )
        return _applied(RunStatus.CANCELLED)

    if resolution is RecoveryResolution.FAIL:
        if reason == "UNKNOWN_RESULT" or not irrecoverable_confirmed:
            return _reject(
                ResultCode.RESOLUTION_NOT_ALLOWED,
                current_status,
                "FAIL requires an allowed reason and confirmed irrecoverability",
            )
        if unresolved_external_effect_count:
            return _reject(
                ResultCode.RESOLUTION_NOT_ALLOWED,
                current_status,
                "FAIL requires resolved external delivery uncertainty",
            )
        return _applied(RunStatus.FAILED)

    return _reject(ResultCode.RESOLUTION_NOT_ALLOWED, current_status, "unknown recovery resolution")


def _resolve_recheck(
    *,
    reason: RecoveryReasonV1,
    pre_recovery_status: RunStatus,
    recheck_input_changed: bool,
    recovered_action_status: ActionStatus | None,
    validated_resume_status: RunStatus | None,
) -> RecoveryResolutionDecision:
    if not recheck_input_changed:
        return _reject(
            ResultCode.NO_PROGRESS,
            RunStatus.RECOVERY_REQUIRED,
            "RECHECK requires changed recovery input",
        )
    if reason == "UNKNOWN_RESULT":
        if recovered_action_status is ActionStatus.EXECUTED:
            return _applied(RunStatus.VERIFYING)
        if recovered_action_status is ActionStatus.FAILED:
            return _applied(pre_recovery_status)
        return _reject(
            ResultCode.NO_PROGRESS,
            RunStatus.RECOVERY_REQUIRED,
            "UNKNOWN_RESULT remains unresolved after recheck",
        )
    if reason == "VERIFICATION_MISMATCH":
        return _applied(RunStatus.VERIFYING)
    if reason in {"CHECKPOINT_MISMATCH", "CONTRACT_VIOLATION"}:
        if (
            validated_resume_status is None
            or validated_resume_status is not pre_recovery_status
            or validated_resume_status is RunStatus.RECOVERY_REQUIRED
        ):
            return _reject(
                ResultCode.NO_PROGRESS,
                RunStatus.RECOVERY_REQUIRED,
                "RECHECK requires the validated pre-recovery resume status",
            )
        return _applied(validated_resume_status)
    return _reject(ResultCode.NO_PROGRESS, RunStatus.RECOVERY_REQUIRED, "unknown recovery reason")


def _applied(next_status: RunStatus) -> RecoveryResolutionDecision:
    return RecoveryResolutionDecision(True, ResultCode.TRANSITION_APPLIED, next_status)


def _reject(
    result_code: ResultCode, current_status: RunStatus, detail: str
) -> RecoveryResolutionDecision:
    return RecoveryResolutionDecision(False, result_code, current_status, detail)
