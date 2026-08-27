"""Action persistence port."""

from typing import Protocol

from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import ActionStatusV1


class ActionRepository(Protocol):
    def get_by_id(self, action_id: str) -> ActionRecord | None: ...
    def insert_read_action(self, action: ActionRecord) -> None: ...
    def insert_write_action(self, action: ActionRecord) -> None: ...
    def update_if_version_and_status(
        self,
        action_id: str,
        *,
        expected_version: int,
        expected_status: ActionStatusV1,
        next_status: ActionStatusV1,
        updated_at_ms: int,
        arguments_json: str | None = None,
        arguments_hash: str | None = None,
        risk: dict[str, object] | None = None,
    ) -> ActionRecord | None: ...
    def list_by_plan(self, plan_id: str) -> tuple[ActionRecord, ...]: ...
    def list_ready_actions(self, plan_id: str) -> tuple[ActionRecord, ...]: ...
    def connector_id_for_action(self, action_id: str) -> str: ...
