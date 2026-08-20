"""Connector identity bindings for the legacy persistence compatibility boundary.

Canonical Tool Route owns connector selection. The current release still
passes legacy Action DTOs that do not carry ``connector_id`` themselves, so
this module transports the already-frozen identity across that narrow
compatibility boundary without re-selecting or inferring a connector.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar

from google_work_agent.adapters.persistence.repositories import (
    SQLiteActionRepository,
    SQLiteResourceRefRepository,
)
from google_work_agent.domain import canonicalize_action_risk
from google_work_agent.ports import ActionRecord, ResourceRefRecord

_GOOGLE_WORKSPACE_CONNECTOR_ID = "google_workspace"

_action_connectors: ContextVar[Mapping[str, str] | None] = ContextVar(
    "action_connectors", default=None
)
_resource_connector: ContextVar[str | None] = ContextVar(
    "resource_connector", default=None
)


@contextmanager
def bind_action_connector_ids(connector_ids: Mapping[str, str]) -> Iterator[None]:
    """Bind code-owned action connector identities for one persistence call."""

    normalized = {
        str(action_id): str(connector_id)
        for action_id, connector_id in connector_ids.items()
    }
    if not normalized or any(
        not action_id or not connector_id
        for action_id, connector_id in normalized.items()
    ):
        raise ValueError("action connector binding requires non-empty action and connector ids")
    token = _action_connectors.set(normalized)
    try:
        yield
    finally:
        _action_connectors.reset(token)


@contextmanager
def bind_resource_connector_id(connector_id: str) -> Iterator[None]:
    """Bind the persisted Action connector while its result ResourceRef is stored."""

    if not connector_id:
        raise ValueError("resource connector binding requires a non-empty connector id")
    token = _resource_connector.set(connector_id)
    try:
        yield
    finally:
        _resource_connector.reset(token)


class ConnectorAwareActionRepository(SQLiteActionRepository):
    """Action repository that writes the frozen connector identity explicitly."""

    def _insert_action(self, action: ActionRecord) -> None:
        bindings = _action_connectors.get()
        connector_id = bindings.get(action.id) if bindings is not None else None
        # Compatibility-only fallback for legacy Google-only callers. The
        # canonical ACTION runtime always enters bind_action_connector_ids.
        connector_id = connector_id or _GOOGLE_WORKSPACE_CONNECTOR_ID
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
                connector_id,
            ),
        )

    def connector_id_for_action(self, action_id: str) -> str:
        row = self._connection.execute(
            "SELECT connector_id FROM actions WHERE id = ?;",
            (action_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"action not found: {action_id}")
        connector_id = str(row["connector_id"])
        if not connector_id:
            raise sqlite3.IntegrityError("persisted action connector_id is empty")
        return connector_id


class ConnectorAwareResourceRefRepository(SQLiteResourceRefRepository):
    """ResourceRef repository using connector-aware canonical identity when bound."""

    def get_by_unique_key(
        self,
        *,
        run_id: str,
        source: str,
        resource_type: str,
        resource_id: str,
    ) -> ResourceRefRecord | None:
        connector_id = _resource_connector.get()
        if connector_id is None:
            return super().get_by_unique_key(
                run_id=run_id,
                source=source,
                resource_type=resource_type,
                resource_id=resource_id,
            )
        row = self._connection.execute(
            """
            SELECT id
            FROM resource_refs
            WHERE run_id = ? AND connector_id = ? AND resource_type = ? AND resource_id = ?;
            """,
            (run_id, connector_id, resource_type, resource_id),
        ).fetchone()
        if row is None:
            return None
        return super().get_by_id(str(row["id"]))

    def upsert(self, record: ResourceRefRecord) -> None:
        connector_id = _resource_connector.get() or _GOOGLE_WORKSPACE_CONNECTOR_ID
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
                connector_id,
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

    def connector_id_for_resource_ref(self, resource_ref_id: str) -> str:
        row = self._connection.execute(
            "SELECT connector_id FROM resource_refs WHERE id = ?;",
            (resource_ref_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"resource ref not found: {resource_ref_id}")
        return str(row["connector_id"])
