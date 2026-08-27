"""Approval persistence port."""

from typing import Protocol

from google_work_agent.domain.approval.model import Approval as ApprovalRecord
from google_work_agent.domain.approval.model import ApprovalStatusV1


class ApprovalRepository(Protocol):
    def get_active_for_action(self, action_id: str) -> ApprovalRecord | None: ...
    def insert_active_snapshot(self, record: ApprovalRecord) -> None: ...
    def list_active_for_plan(self, plan_id: str) -> tuple[ApprovalRecord, ...]: ...
    def update_if_status(
        self,
        approval_id: str,
        expected_status: ApprovalStatusV1,
        values: dict[str, object],
    ) -> bool: ...


def active_approval_tuple(
    repository: ApprovalRepository, action_id: str
) -> tuple[ApprovalRecord, ...]:
    active = repository.get_active_for_action(action_id)
    return () if active is None else (active,)
