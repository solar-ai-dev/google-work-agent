"""Connector-aware SQLite repositories with explicit persistence identity.

Tool Route owns connector selection.  Persistence accepts that identity only
through ``ActionRecord.connector_id`` and ``ResourceRefRecord.connector_id``;
there is no ContextVar transport, source inference, or Google fallback.
"""

from __future__ import annotations

import sqlite3
from json import loads

from google_work_agent.adapters.persistence.repositories import (
    SQLiteActionRepository,
    SQLiteResourceRefRepository,
)
from google_work_agent.domain import canonicalize_action_risk
from google_work_agent.ports import (
    ActionRecord,
    ResourceRefRecord,
    ResourceSource,
    StoredResourceType,
)


class ConnectorAwareActionRepository(SQLiteActionRepository):
    """Persist and hydrate the connector selected by the frozen Tool Route."""

    def _insert_action(self, action: ActionRecord) -> None:
        if not action.connector_id:
            raise ValueError("action persistence requires connector_id")
        self._connection.execute(
            """
            INSERT INTO actions (
                id, plan_id, position, tool_name, effect_type, approval_requirement,
                verification_policy, recovery_policy, target_resource_ref_id, status,
                arguments_json, arguments_hash, expected_json, risk_json, version,
                created_at_ms, updated_at_ms, connector_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
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

    def get_by_id(self, action_id: str) -> ActionRecord | None:
        row = self._connection.execute(
            """
            SELECT id, plan_id, connector_id, position, tool_name, effect_type,
                   approval_requirement, verification_policy, recovery_policy,
                   target_resource_ref_id, status, arguments_json, arguments_hash,
                   expected_json, risk_json, version, created_at_ms, updated_at_ms
            FROM actions WHERE id = ?;
            """,
            (action_id,),
        ).fetchone()
        return None if row is None else self._record(row)

    def list_by_plan(self, plan_id: str) -> tuple[ActionRecord, ...]:
        rows = self._connection.execute(
            """
            SELECT id, plan_id, connector_id, position, tool_name, effect_type,
                   approval_requirement, verification_policy, recovery_policy,
                   target_resource_ref_id, status, arguments_json, arguments_hash,
                   expected_json, risk_json, version, created_at_ms, updated_at_ms
            FROM actions WHERE plan_id = ? ORDER BY position ASC;
            """,
            (plan_id,),
        ).fetchall()
        return tuple(self._record(row) for row in rows)

    def list_ready_actions(self, plan_id: str) -> tuple[ActionRecord, ...]:
        rows = self._connection.execute(
            """
            SELECT a.id, a.plan_id, a.connector_id, a.position, a.tool_name, a.effect_type,
                   a.approval_requirement, a.verification_policy, a.recovery_policy,
                   a.target_resource_ref_id, a.status, a.arguments_json, a.arguments_hash,
                   a.expected_json, a.risk_json, a.version, a.created_at_ms, a.updated_at_ms
            FROM actions AS a
            WHERE a.plan_id = ?
              AND a.status = 'PROPOSED'
              AND NOT EXISTS (
                    SELECT 1
                    FROM action_dependencies AS d
                    JOIN actions AS dep ON dep.id = d.depends_on_action_id
                    WHERE d.action_id = a.id AND dep.status <> 'VERIFIED'
              )
            ORDER BY a.position ASC;
            """,
            (plan_id,),
        ).fetchall()
        return tuple(self._record(row) for row in rows)

    def connector_id_for_action(self, action_id: str) -> str:
        action = self.get_by_id(action_id)
        if action is None:
            raise LookupError(f"action not found: {action_id}")
        return action.connector_id

    @staticmethod
    def _record(row: sqlite3.Row) -> ActionRecord:
        risk = loads(str(row["risk_json"]))
        if not isinstance(risk, dict):
            raise sqlite3.IntegrityError("action risk_json must decode to an object")
        return ActionRecord(
            id=str(row["id"]),
            plan_id=str(row["plan_id"]),
            connector_id=str(row["connector_id"]),
            position=int(row["position"]),
            tool_name=str(row["tool_name"]),
            effect_type=str(row["effect_type"]),
            approval_requirement=str(row["approval_requirement"]),
            verification_policy=str(row["verification_policy"]),
            recovery_policy=str(row["recovery_policy"]),
            target_resource_ref_id=(
                None if row["target_resource_ref_id"] is None else str(row["target_resource_ref_id"])
            ),
            status=str(row["status"]),
            arguments_json=str(row["arguments_json"]),
            arguments_hash=str(row["arguments_hash"]),
            expected_json=str(row["expected_json"]),
            risk=risk,
            version=int(row["version"]),
            created_at_ms=int(row["created_at_ms"]),
            updated_at_ms=int(row["updated_at_ms"]),
        )


class ConnectorAwareResourceRefRepository(SQLiteResourceRefRepository):
    """ResourceRef repository keyed only by canonical connector identity."""

    _SELECT = """
        SELECT id, run_id, connector_id, source, resource_type, resource_id,
               parent_resource_id, canonical_url, title, event_time_ms,
               version_token, metadata_json, captured_at_ms
        FROM resource_refs
    """

    def get_by_id(self, resource_ref_id: str) -> ResourceRefRecord | None:
        row = self._connection.execute(
            self._SELECT + " WHERE id = ?;", (resource_ref_id,)
        ).fetchone()
        return None if row is None else self._record(row)

    def get_by_unique_key(
        self,
        *,
        run_id: str,
        connector_id: str,
        resource_type: str,
        resource_id: str,
    ) -> ResourceRefRecord | None:
        if not connector_id:
            raise ValueError("resource reference lookup requires connector_id")
        row = self._connection.execute(
            self._SELECT
            + " WHERE run_id = ? AND connector_id = ? AND resource_type = ? AND resource_id = ?;",
            (run_id, connector_id, resource_type, resource_id),
        ).fetchone()
        return None if row is None else self._record(row)

    def upsert(self, record: ResourceRefRecord) -> None:
        if not record.connector_id:
            raise ValueError("resource reference persistence requires connector_id")
        self._connection.execute(
            """
            INSERT INTO resource_refs (
                id, run_id, connector_id, source, resource_type, resource_id,
                parent_resource_id, canonical_url, title, event_time_ms,
                version_token, metadata_json, captured_at_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, connector_id, resource_type, resource_id)
            DO UPDATE SET
                source = excluded.source,
                parent_resource_id = excluded.parent_resource_id,
                canonical_url = excluded.canonical_url,
                title = excluded.title,
                event_time_ms = excluded.event_time_ms,
                version_token = excluded.version_token,
                metadata_json = excluded.metadata_json,
                captured_at_ms = excluded.captured_at_ms;
            """,
            (
                record.id,
                record.run_id,
                record.connector_id,
                record.source.value,
                record.resource_type.value,
                record.resource_id,
                record.parent_resource_id,
                record.canonical_url,
                record.title,
                record.event_time_ms,
                record.version_token,
                record.metadata_json,
                record.captured_at_ms,
            ),
        )

    def list_by_run(self, run_id: str) -> tuple[ResourceRefRecord, ...]:
        rows = self._connection.execute(
            self._SELECT
            + " WHERE run_id = ? ORDER BY connector_id, source, resource_type, resource_id;",
            (run_id,),
        ).fetchall()
        return tuple(self._record(row) for row in rows)

    def connector_id_for_resource_ref(self, resource_ref_id: str) -> str:
        record = self.get_by_id(resource_ref_id)
        if record is None:
            raise LookupError(f"resource ref not found: {resource_ref_id}")
        return record.connector_id

    @staticmethod
    def _record(row: sqlite3.Row) -> ResourceRefRecord:
        return ResourceRefRecord(
            id=str(row["id"]),
            run_id=str(row["run_id"]),
            connector_id=str(row["connector_id"]),
            source=ResourceSource(str(row["source"])),
            resource_type=StoredResourceType(str(row["resource_type"])),
            resource_id=str(row["resource_id"]),
            parent_resource_id=(
                None if row["parent_resource_id"] is None else str(row["parent_resource_id"])
            ),
            canonical_url=None if row["canonical_url"] is None else str(row["canonical_url"]),
            title=None if row["title"] is None else str(row["title"]),
            event_time_ms=None if row["event_time_ms"] is None else int(row["event_time_ms"]),
            version_token=None if row["version_token"] is None else str(row["version_token"]),
            metadata_json=str(row["metadata_json"]),
            captured_at_ms=int(row["captured_at_ms"]),
        )