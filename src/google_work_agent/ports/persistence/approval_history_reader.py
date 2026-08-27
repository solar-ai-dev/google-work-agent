"""Read-only projection for an Approval identified by durable id."""

from typing import Protocol

from google_work_agent.domain.approval.model import Approval


class ApprovalHistoryReader(Protocol):
    def get(self, approval_id: str) -> Approval | None: ...
    def list_for_action(self, action_id: str) -> tuple[Approval, ...]: ...
