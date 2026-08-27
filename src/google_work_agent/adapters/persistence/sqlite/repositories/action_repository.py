"""SQLite action repository with connector-aware identity."""

import sqlite3

from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import (
    ActionStatusV1,
    canonicalize_action_risk,
    parse_action_risk_json,
)


class SQLiteActionRepository:
    _SELECT = "SELECT id, plan_id, connector_id, position, tool_name, effect_type, approval_requirement, verification_policy, recovery_policy, target_resource_ref_id, status, arguments_json, arguments_hash, expected_json, risk_json, version, created_at_ms, updated_at_ms FROM actions"  # noqa: E501

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @staticmethod
    def _record(r: sqlite3.Row) -> ActionRecord:
        risk = parse_action_risk_json(str(r["risk_json"]))
        return ActionRecord(
            id=str(r["id"]),
            plan_id=str(r["plan_id"]),
            connector_id=str(r["connector_id"]),
            position=int(r["position"]),
            tool_name=str(r["tool_name"]),
            effect_type=str(r["effect_type"]),
            approval_requirement=str(r["approval_requirement"]),
            verification_policy=str(r["verification_policy"]),
            recovery_policy=str(r["recovery_policy"]),
            target_resource_ref_id=None
            if r["target_resource_ref_id"] is None
            else str(r["target_resource_ref_id"]),
            status=str(r["status"]),
            arguments_json=str(r["arguments_json"]),
            arguments_hash=str(r["arguments_hash"]),
            expected_json=str(r["expected_json"]),
            risk=risk,
            version=int(r["version"]),
            created_at_ms=int(r["created_at_ms"]),
            updated_at_ms=int(r["updated_at_ms"]),
        )

    def get_by_id(self, action_id: str) -> ActionRecord | None:
        r = self._connection.execute(self._SELECT + " WHERE id=?;", (action_id,)).fetchone()
        return None if r is None else self._record(r)

    def _insert(self, action: ActionRecord) -> None:
        if not action.connector_id:
            raise ValueError("action persistence requires connector_id")
        self._connection.execute(
            "INSERT INTO actions (id, plan_id, position, tool_name, effect_type, approval_requirement, verification_policy, recovery_policy, target_resource_ref_id, status, arguments_json, arguments_hash, expected_json, risk_json, version, created_at_ms, updated_at_ms, connector_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",  # noqa: E501
            (
                action.id,
                action.plan_id,
                action.position,
                action.tool_name,
                action.effect_type,
                action.approval_requirement,
                action.verification_policy,
                action.recovery_policy,
                action.target_resource_ref_id,
                action.status,
                action.arguments_json,
                action.arguments_hash,
                action.expected_json,
                canonicalize_action_risk(action.risk),
                action.version,
                action.created_at_ms,
                action.updated_at_ms,
                action.connector_id,
            ),
        )

    def insert_read_action(self, action: ActionRecord) -> None:
        self._insert(action)

    def insert_write_action(self, action: ActionRecord) -> None:
        self._insert(action)

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
    ) -> ActionRecord | None:
        current = self.get_by_id(action_id)
        if current is None:
            return None
        cursor = self._connection.execute(
            "UPDATE actions SET status=?, version=version+1, updated_at_ms=?, arguments_json=COALESCE(?, arguments_json), arguments_hash=COALESCE(?, arguments_hash), risk_json=COALESCE(?, risk_json) WHERE id=? AND version=? AND status=?;",  # noqa: E501
            (
                next_status.value,
                updated_at_ms,
                arguments_json,
                arguments_hash,
                None if risk is None else canonicalize_action_risk(risk),
                action_id,
                expected_version,
                expected_status.value,
            ),
        )
        if cursor.rowcount != 1:
            return None
        return self.get_by_id(action_id)

    def list_by_plan(self, plan_id: str) -> tuple[ActionRecord, ...]:
        return tuple(
            self._record(r)
            for r in self._connection.execute(
                self._SELECT + " WHERE plan_id=? ORDER BY position ASC;", (plan_id,)
            ).fetchall()
        )

    def list_ready_actions(self, plan_id: str) -> tuple[ActionRecord, ...]:
        rows = self._connection.execute(
            self._SELECT
            + " AS a WHERE a.plan_id=? AND a.status='PROPOSED' AND NOT EXISTS (SELECT 1 FROM action_dependencies AS d JOIN actions AS dep ON dep.id=d.depends_on_action_id WHERE d.action_id=a.id AND dep.status <> 'VERIFIED') ORDER BY a.position ASC;",  # noqa: E501
            (plan_id,),
        ).fetchall()
        return tuple(self._record(r) for r in rows)

    def connector_id_for_action(self, action_id: str) -> str:
        action = self.get_by_id(action_id)
        if action is None:
            raise LookupError(f"action not found: {action_id}")
        return action.connector_id
