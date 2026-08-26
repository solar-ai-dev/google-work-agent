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
