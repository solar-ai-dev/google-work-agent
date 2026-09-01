"""Canonical reason-aware Recovery resolution transition."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.recovery.guards.resolve_recovery import guard_resolve_recovery
from google_work_agent.domain.recovery.model import (
    RECOVERY_RESOLUTION_MATRIX,
    RecoveryReasonV1,
    RecoveryResolution,
)
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected


@dataclass(frozen=True, slots=True)
class RecoveryResolutionDecision:
    applied: bool
    result_code: ResultCode
    current_status: RunStatusV1
    conflict_detail: str | None = None
    reopen_verification_action: bool = False


def allowed_recovery_resolutions(
    *,
    reason: RecoveryReasonV1,
    recovered_action_status: ActionStatusV1 | None = None,
    cancel_intent_active: bool = False,
    unresolved_external_effect_count: int = 0,
    irrecoverable_confirmed: bool = False,
) -> tuple[RecoveryResolution, ...]:
    """Return the single Domain-owned resolution eligibility projection."""
    return tuple(
        resolution
        for resolution in RECOVERY_RESOLUTION_MATRIX[reason]
        if not (
            resolution
            in {RecoveryResolution.ACCEPT_PARTIAL, RecoveryResolution.CREATE_CORRECTIVE_PLAN}
            and cancel_intent_active
        )
        if not (
            resolution is RecoveryResolution.CANCEL
            and (
                not cancel_intent_active
                or unresolved_external_effect_count != 0
                or (
                    reason == "UNKNOWN_RESULT"
                    and recovered_action_status
                    not in {ActionStatusV1.EXECUTED, ActionStatusV1.FAILED}
                )
            )
        )
        if not (
            resolution is RecoveryResolution.FAIL
            and (
                cancel_intent_active
                or unresolved_external_effect_count != 0
                or not irrecoverable_confirmed
            )
        )
    )


def transition_resolve_recovery(
    current_status: RunStatusV1,
    *,
    resolution: RecoveryResolution,
    reason: RecoveryReasonV1,
    pre_recovery_status: RunStatusV1,
    recheck_input_changed: bool = False,
    recovered_action_status: ActionStatusV1 | None = None,
    validated_resume_status: RunStatusV1 | None = None,
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

    if resolution not in allowed_recovery_resolutions(
        reason=reason,
        recovered_action_status=recovered_action_status,
        cancel_intent_active=cancel_intent_active,
        unresolved_external_effect_count=unresolved_external_effect_count,
        irrecoverable_confirmed=irrecoverable_confirmed,
    ):
        return _reject(
            ResultCode.RESOLUTION_NOT_ALLOWED,
            current_status,
            f"{resolution.value} is not eligible for the current durable Recovery facts",
        )

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
        return _applied(
            RunStatusV1.COMPLETED
            if resolution is RecoveryResolution.ACCEPT_PARTIAL
            else RunStatusV1.PLANNING
        )

    if resolution is RecoveryResolution.CANCEL:
        return _applied(RunStatusV1.CANCELLED)

    if resolution is RecoveryResolution.FAIL:
        return _applied(RunStatusV1.FAILED)

    return _reject(ResultCode.RESOLUTION_NOT_ALLOWED, current_status, "unknown recovery resolution")


def _resolve_recheck(
    *,
    reason: RecoveryReasonV1,
    pre_recovery_status: RunStatusV1,
    recheck_input_changed: bool,
    recovered_action_status: ActionStatusV1 | None,
    validated_resume_status: RunStatusV1 | None,
) -> RecoveryResolutionDecision:
    if not recheck_input_changed:
        return _reject(
            ResultCode.NO_PROGRESS,
            RunStatusV1.RECOVERY_REQUIRED,
            "RECHECK requires changed recovery input",
        )
    if reason == "UNKNOWN_RESULT":
        if recovered_action_status is ActionStatusV1.EXECUTED:
            return _applied(RunStatusV1.VERIFYING)
        if recovered_action_status is ActionStatusV1.FAILED:
            return _applied(pre_recovery_status)
        return _reject(
            ResultCode.NO_PROGRESS,
            RunStatusV1.RECOVERY_REQUIRED,
            "UNKNOWN_RESULT remains unresolved after recheck",
        )
    if reason == "VERIFICATION_MISMATCH":
        return _applied(
            RunStatusV1.VERIFYING,
            reopen_verification_action=True,
        )
    if reason in {"CHECKPOINT_MISMATCH", "CONTRACT_VIOLATION"}:
        if (
            validated_resume_status is None
            or validated_resume_status is not pre_recovery_status
            or validated_resume_status is RunStatusV1.RECOVERY_REQUIRED
        ):
            return _reject(
                ResultCode.NO_PROGRESS,
                RunStatusV1.RECOVERY_REQUIRED,
                "RECHECK requires the validated pre-recovery resume status",
            )
        return _applied(validated_resume_status)
    return _reject(ResultCode.NO_PROGRESS, RunStatusV1.RECOVERY_REQUIRED, "unknown recovery reason")


def _applied(
    next_status: RunStatusV1,
    *,
    reopen_verification_action: bool = False,
) -> RecoveryResolutionDecision:
    return RecoveryResolutionDecision(
        True,
        ResultCode.TRANSITION_APPLIED,
        next_status,
        reopen_verification_action=reopen_verification_action,
    )


def _reject(
    result_code: ResultCode, current_status: RunStatusV1, detail: str
) -> RecoveryResolutionDecision:
    return RecoveryResolutionDecision(False, result_code, current_status, detail)
