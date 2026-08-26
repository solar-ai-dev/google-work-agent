"""Replay reservation boundary for non-Domain operational side effects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class OperationalCommandContextV1:
    command_id: str
    operation_kind: str
    request_hash: str


@dataclass(frozen=True, slots=True)
class OperationalReplayDecisionV2:
    kind: Literal["RESERVED", "COMPLETED", "RECOVER_RESERVED", "CONFLICT"]
    operation_ref: str
    result_ref: str | None = None
    bounded_result: Mapping[str, object] | None = None


class OperationalCommandReplayPort(Protocol):
    def reserve_or_replay(
        self, context: OperationalCommandContextV1
    ) -> OperationalReplayDecisionV2: ...

    def mark_uncertain(self, context: OperationalCommandContextV1, recovery_ref: str) -> None: ...

    def store_result(
        self,
        context: OperationalCommandContextV1,
        result_ref: str,
        bounded_result: Mapping[str, object],
    ) -> None: ...
