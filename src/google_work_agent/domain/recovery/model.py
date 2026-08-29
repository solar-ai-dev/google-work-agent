"""Domain recovery vocabulary (04-A State Transition Contract: RecoveryContextV1)."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

RecoveryReasonV1 = Literal[
    "UNKNOWN_RESULT", "VERIFICATION_MISMATCH", "CHECKPOINT_MISMATCH", "CONTRACT_VIOLATION"
]


class RecoveryResolution(StrEnum):
    """Registered Run recovery variants from the canonical transition contract."""

    RECHECK = "RECHECK"
    ACCEPT_PARTIAL = "ACCEPT_PARTIAL"
    CREATE_CORRECTIVE_PLAN = "CREATE_CORRECTIVE_PLAN"
    CANCEL = "CANCEL"
    FAIL = "FAIL"


RECOVERY_RESOLUTION_MATRIX: dict[RecoveryReasonV1, tuple[RecoveryResolution, ...]] = {
    "UNKNOWN_RESULT": (RecoveryResolution.RECHECK, RecoveryResolution.CANCEL),
    "VERIFICATION_MISMATCH": (
        RecoveryResolution.RECHECK,
        RecoveryResolution.ACCEPT_PARTIAL,
        RecoveryResolution.CREATE_CORRECTIVE_PLAN,
        RecoveryResolution.CANCEL,
        RecoveryResolution.FAIL,
    ),
    "CHECKPOINT_MISMATCH": (
        RecoveryResolution.RECHECK,
        RecoveryResolution.CANCEL,
        RecoveryResolution.FAIL,
    ),
    "CONTRACT_VIOLATION": (
        RecoveryResolution.RECHECK,
        RecoveryResolution.CANCEL,
        RecoveryResolution.FAIL,
    ),
}


def validate_recovery_context_shape(
    *,
    reason: RecoveryReasonV1,
    scope: str,
    recovery_fingerprint: str,
    action_id: str | None,
    execution_attempt_id: str | None,
    verification_id: str | None,
    registered_resume_target_present: bool,
    observed_external_state_fingerprint: str | None,
    verification_input_fingerprint: str | None,
    contract_or_checkpoint_fingerprint: str | None,
) -> None:
    """Enforce the closed Canonical reason/scope/reference matrix."""
    if not recovery_fingerprint:
        raise ValueError("RecoveryContext requires a recovery fingerprint")
    if reason == "UNKNOWN_RESULT":
        if (
            scope != "ACTION"
            or not action_id
            or not execution_attempt_id
            or verification_id is not None
            or observed_external_state_fingerprint is not None
            or verification_input_fingerprint is not None
            or contract_or_checkpoint_fingerprint is not None
        ):
            raise ValueError(
                "UNKNOWN_RESULT requires ACTION + Action + Attempt without foreign reason facts"
            )
        return
    if reason == "VERIFICATION_MISMATCH":
        if (
            scope != "ACTION"
            or not action_id
            or not execution_attempt_id
            or not verification_id
            or not observed_external_state_fingerprint
            or not verification_input_fingerprint
            or contract_or_checkpoint_fingerprint is not None
        ):
            raise ValueError(
                "VERIFICATION_MISMATCH requires ACTION + Action + Attempt + Verification facts"
            )
        return
    if (
        scope != "RUN"
        or any((action_id, execution_attempt_id, verification_id))
        or observed_external_state_fingerprint is not None
        or verification_input_fingerprint is not None
    ):
        raise ValueError(f"{reason} requires RUN scope without child references")
    if not contract_or_checkpoint_fingerprint:
        raise ValueError(f"{reason} requires a contract/checkpoint fingerprint")
    if reason == "CHECKPOINT_MISMATCH" and not registered_resume_target_present:
        raise ValueError("CHECKPOINT_MISMATCH requires a registered resume target")
