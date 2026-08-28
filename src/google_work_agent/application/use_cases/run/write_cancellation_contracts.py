"""Run-owner-local cancellation contracts for write execution."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RequestRunCancellationCommand:
    command_id: str
    request_hash: str
    run_id: str
    expected_run_version: int


@dataclass(frozen=True, slots=True)
class FinalizeRunCancellationCommand:
    command_id: str
    request_hash: str
    run_id: str
    expected_run_version: int
