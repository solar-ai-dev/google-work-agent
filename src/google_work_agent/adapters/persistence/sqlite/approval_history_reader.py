"""SQLite Approval history projection without widening ApprovalRepository."""

from google_work_agent.adapters.persistence.sqlite.repositories.approval_repository import (
    SqliteApprovalRepository,
)
from google_work_agent.domain.approval.model import Approval


class SqliteApprovalHistoryReader:
    def __init__(self, approvals: SqliteApprovalRepository) -> None:
        self._approvals = approvals

    def get(self, approval_id: str) -> Approval | None:
        return self._approvals._get_by_id(approval_id)

    def list_for_action(self, action_id: str) -> tuple[Approval, ...]:
        return self._approvals._list_for_action(action_id)
