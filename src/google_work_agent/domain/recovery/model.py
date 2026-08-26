"""Domain recovery vocabulary (04-A State Transition Contract: RecoveryContextV1)."""

from __future__ import annotations

from typing import Literal

RecoveryReasonV1 = Literal[
    "UNKNOWN_RESULT", "VERIFICATION_MISMATCH", "CHECKPOINT_MISMATCH", "CONTRACT_VIOLATION"
]
