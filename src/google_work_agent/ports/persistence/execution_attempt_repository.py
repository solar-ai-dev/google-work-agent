"""Execution-attempt persistence port."""

from dataclasses import dataclass
from typing import Literal, Protocol

from google_work_agent.domain import ExecutionAttemptStatus
from google_work_agent.ports.models import ExecutionAttemptRecord

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
    def get_by_id(self, attempt_id: str) -> ExecutionAttemptRecord | None: ...
    def get_active_by_approval(self, approval_id: str) -> ExecutionAttemptRecord | None: ...
    def insert_claimed(self, record: ExecutionAttemptRecord) -> None: ...
    def mark_succeeded(
        self,
        attempt_id: str,
        *,
        expected_version: int,
        result_resource_ref_id: str | None,
        response_metadata_json: str | None,
        finished_at_ms: int,
    ) -> ExecutionAttemptRecord: ...
    def mark_failed(
        self,
        attempt_id: str,
        *,
        expected_version: int,
        error_code: str,
        error_detail_json: str,
        finished_at_ms: int,
    ) -> ExecutionAttemptRecord: ...
    def mark_unknown_result(
        self,
        attempt_id: str,
        *,
        expected_version: int,
        error_code: str,
        error_detail_json: str,
        finished_at_ms: int,
    ) -> ExecutionAttemptRecord: ...
    def update_status(
        self,
        attempt_id: str,
        *,
        expected_version: int,
        status: ExecutionAttemptStatus,
        error_code: str | None,
        error_detail_json: str | None,
        result_resource_ref_id: str | None,
        response_metadata_json: str | None,
        finished_at_ms: int | None,
    ) -> ExecutionAttemptRecord: ...
    def list_by_approval(self, approval_id: str) -> tuple[ExecutionAttemptRecord, ...]: ...
    def list_reconciliation_candidates(
        self, limit: int
    ) -> tuple[ExecutionReconciliationCandidateV1, ...]: ...
