"""Typed non-Domain operational replay values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class OperationalCommandContextV1:
    command_id: str
    operation_kind: str
    canonical_request_hash: str

    def __post_init__(self) -> None:
        if not self.command_id.strip() or not self.operation_kind.strip():
            raise ValueError("command_id and operation_kind are required")
        if len(self.canonical_request_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.canonical_request_hash
        ):
            raise ValueError("canonical_request_hash must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class OperationalReplayDecisionV2:
    decision: Literal["PROCEED_NEW", "REPLAY_COMPLETED", "RECOVER_RESERVED", "CONFLICT"]
    reservation_status: Literal["RESERVED", "UNCERTAIN", "COMPLETED"] | None
    operation_ref: str | None
    stored_result_ref: str | None
    recovery_ref: str | None
    bounded_result: JsonValue | None = None


@dataclass(frozen=True, slots=True)
class OperationalReconcileResultV1:
    status: Literal["COMPLETED", "SAFE_TO_RETRY", "UNCERTAIN"]
    result_ref: str | None
    bounded_result: JsonValue | None


__all__ = [
    "JsonValue",
    "OperationalCommandContextV1",
    "OperationalReconcileResultV1",
    "OperationalReplayDecisionV2",
]
