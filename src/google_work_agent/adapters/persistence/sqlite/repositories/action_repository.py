"""SQLite action repository with connector-aware identity."""

import sqlite3

from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import (
    ActionStatusV1,
    canonicalize_action_risk,
    parse_action_risk_json,
)


class SqliteActionRepository:
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

    def get(self, action_id: str) -> ActionRecord | None:
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

    def insert_for_plan(
        self,
        action: ActionRecord,
        *,
        dependency_ids: tuple[str, ...] = (),
        evidence_ids: tuple[str, ...] = (),
    ) -> None:
        self._insert(action)
        self._connection.executemany(
            "INSERT INTO action_dependencies (action_id, depends_on_action_id) VALUES (?, ?);",
            ((action.id, dependency_id) for dependency_id in dependency_ids),
        )
        self._connection.executemany(
            "INSERT OR IGNORE INTO action_evidence (action_id, evidence_id) VALUES (?, ?);",
            ((action.id, evidence_id) for evidence_id in evidence_ids),
        )

    def list_dependents(self, action_id: str) -> tuple[str, ...]:
        rows = self._connection.execute(
            "SELECT action_id FROM action_dependencies WHERE depends_on_action_id=? "
            "ORDER BY action_id ASC;", (action_id,)
        ).fetchall()
        return tuple(str(row["action_id"]) for row in rows)

    def is_dependency_ready(self, action_id: str) -> bool:
        return self._connection.execute(
            "SELECT 1 FROM action_dependencies AS d JOIN actions AS dependency "
            "ON dependency.id=d.depends_on_action_id WHERE d.action_id=? "
            "AND dependency.status <> 'VERIFIED' LIMIT 1;", (action_id,)
        ).fetchone() is None

    def update_if_version_and_status(
        self,
        action_id: str,
        expected_version: int,
        expected_statuses: frozenset[ActionStatusV1],
        values: dict[str, object],
    ) -> bool:
        if not values or not expected_statuses:
            raise ValueError("Action CAS requires values and expected statuses")
        allowed_columns = {
            "status",
            "version",
            "updated_at_ms",
            "arguments_json",
            "arguments_hash",
            "risk_json",
        }
        if not set(values).issubset(allowed_columns):
            raise ValueError("Action CAS contains an unsupported column")
        normalized = {
            key: value.value if isinstance(value, ActionStatusV1) else value
            for key, value in values.items()
        }
        set_clause = ", ".join(f"{column}=?" for column in normalized)
        placeholders = ", ".join("?" for _ in expected_statuses)
        cursor = self._connection.execute(
            f"UPDATE actions SET {set_clause} WHERE id=? AND version=? "
            f"AND status IN ({placeholders});",
            [
                *normalized.values(),
                action_id,
                expected_version,
                *(status.value for status in expected_statuses),
            ],
        )
        return cursor.rowcount == 1

    def list_for_plan(self, plan_id: str) -> tuple[ActionRecord, ...]:
        return tuple(
            self._record(r)
            for r in self._connection.execute(
                self._SELECT + " WHERE plan_id=? ORDER BY position ASC;", (plan_id,)
            ).fetchall()
        )
