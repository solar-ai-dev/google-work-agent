"""Durable verification model."""

from dataclasses import dataclass
from enum import StrEnum


class VerificationStatus(StrEnum):
    """Only durable verification outcomes; observations are not lifecycle states."""

    VERIFIED = "VERIFIED"
    MISMATCH = "MISMATCH"


class VerificationCommand(StrEnum):
    STORE_VERIFICATION = "STORE_VERIFICATION"


@dataclass(frozen=True, slots=True)
class Verification:
    id: str
    execution_attempt_id: str
    verification_no: int
    status: VerificationStatus
    normalizer_version: str
    expected_json: str
    actual_json: str | None
    diff_json: str
    verified_at_ms: int
