"""Operational approval-validity configuration."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ApprovalPolicyConfigV1:
    approval_ttl_minutes: int

    def __post_init__(self) -> None:
        if self.approval_ttl_minutes < 1:
            raise ValueError("approval_ttl_minutes must be positive")


__all__ = ["ApprovalPolicyConfigV1"]
