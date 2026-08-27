"""Replay reservation boundary for non-Domain operational side effects."""

from __future__ import annotations

from typing import Protocol

from google_work_agent.ports.system.contracts.operational_command_replay import (
    JsonValue,
    OperationalCommandContextV1,
    OperationalReplayDecisionV2,
)


class OperationalCommandReplayPort(Protocol):
    def reserve_or_replay(
        self, context: OperationalCommandContextV1
    ) -> OperationalReplayDecisionV2: ...

    def mark_uncertain(self, context: OperationalCommandContextV1, recovery_ref: str) -> None: ...

    def store_result(
        self,
        context: OperationalCommandContextV1,
        result_ref: str,
        bounded_result: JsonValue,
    ) -> None: ...


__all__ = ["OperationalCommandReplayPort"]
