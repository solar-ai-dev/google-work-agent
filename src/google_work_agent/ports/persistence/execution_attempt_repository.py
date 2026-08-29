"""Execution-attempt persistence port."""

from dataclasses import dataclass
from typing import Literal, Protocol

from google_work_agent.domain.execution_attempt.model import (
    ExecutionAttempt as ExecutionAttemptRecord,
)
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1

type ExecutionReconciliationCandidateKindV1 = Literal[
    "POST_BEGIN_ORPHAN",
    "UNKNOWN_RESULT_UNRESOLVED",
    "EXECUTED_AWAITING_VERIFICATION",
    "FAILED_AWAITING_CONTINUATION",
]


@dataclass(frozen=True, slots=True)
class ExecutionReconciliationCandidateV1:
    schema_version: Literal[1]
    kind: ExecutionReconciliationCandidateKindV1
    execution_attempt_id: str
    action_id: str
    run_id: str


class ExecutionAttemptRepository(Protocol):
    def get(self, attempt_id: str) -> ExecutionAttemptRecord | None: ...
    def get_active_for_approval(self, approval_id: str) -> ExecutionAttemptRecord | None: ...
    def get_latest_for_approval(self, approval_id: str) -> ExecutionAttemptRecord | None: ...
    def insert_claimed(self, record: ExecutionAttemptRecord) -> None: ...
    def update_if_version_and_status(
        self,
        attempt_id: str,
        expected_version: int,
        expected_statuses: frozenset[ExecutionAttemptStatusV1],
        values: dict[str, object],
    ) -> bool: ...
    def list_reconciliation_candidates(
        self, limit: int
    ) -> tuple[ExecutionReconciliationCandidateV1, ...]: ...


def active_attempt_tuple(
    repository: ExecutionAttemptRepository, approval_id: str
) -> tuple[ExecutionAttemptRecord, ...]:
    active = repository.get_active_for_approval(approval_id)
    return () if active is None else (active,)
