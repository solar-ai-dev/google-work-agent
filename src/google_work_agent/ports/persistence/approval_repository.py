"""Approval persistence port."""

from typing import Protocol

from google_work_agent.domain.approval.model import Approval as ApprovalRecord
from google_work_agent.domain.approval.model import ApprovalStatus


class ApprovalRepository(Protocol):
    def get_by_id(self, approval_id: str) -> ApprovalRecord | None: ...
    def get_active_by_action(self, action_id: str) -> ApprovalRecord | None: ...
    def insert(self, record: ApprovalRecord) -> None: ...
    def update_if_status(
        self,
        approval_id: str,
        *,
        expected_status: ApprovalStatus,
        next_status: ApprovalStatus,
        consumed_at_ms: int | None = None,
    ) -> bool: ...
    def list_by_action(self, action_id: str) -> tuple[ApprovalRecord, ...]: ...
