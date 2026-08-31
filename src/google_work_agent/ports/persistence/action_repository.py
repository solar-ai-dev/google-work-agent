"""Action persistence port."""

from typing import Protocol

from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import ActionStatusV1


class ActionRepository(Protocol):
    def get(self, action_id: str) -> ActionRecord | None: ...
    def insert_for_plan(
        self,
        action: ActionRecord,
        *,
        dependency_ids: tuple[str, ...] = (),
        evidence_ids: tuple[str, ...] = (),
    ) -> None: ...
    def list_dependents(self, action_id: str) -> tuple[str, ...]: ...
    def is_dependency_ready(self, action_id: str) -> bool: ...
    def update_if_version_and_status(
        self,
        action_id: str,
        expected_version: int,
        expected_statuses: frozenset[ActionStatusV1],
        values: dict[str, object],
    ) -> bool: ...
    def list_for_plan(self, plan_id: str) -> tuple[ActionRecord, ...]: ...
