"""SQLite realization of the durable RecoveryContextV1 authority."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import asdict
from json import dumps, loads
from typing import Any, cast

from google_work_agent.adapters.persistence.sqlite.repositories.workflow_handoff_repository import (
    deserialize_resume_target,
)
from google_work_agent.ports.persistence.recovery_repository import (
    RecoveryConflictError,
    RecoveryContextV1,
)


class SqliteRecoveryRepository:
    """One canonical current RecoveryContextV1 row per Run."""

    def __init__(
        self, connection: sqlite3.Connection, *, now_ms: Callable[[], int] | None = None
    ) -> None:
        self._connection = connection
        self._now_ms = now_ms or (lambda: time.time_ns() // 1_000_000)

    def store_context(self, context: RecoveryContextV1) -> RecoveryContextV1:
        existing = self._connection.execute(
            "SELECT version FROM recovery_contexts WHERE run_id = ?;", (context["run_id"],)
        ).fetchone()
        if existing is None:
            tombstone = self._connection.execute(
                "SELECT last_version FROM recovery_context_tombstones WHERE run_id = ?;",
                (context["run_id"],),
            ).fetchone()
            expected_version = 0 if tombstone is None else int(tombstone["last_version"]) + 1
            if context["version"] != expected_version:
                raise RecoveryConflictError(
                    "new RecoveryContext version does not follow currentness history"
                )
            self._connection.execute(
                """
                INSERT INTO recovery_contexts (
                    run_id, reason, scope, action_id, execution_attempt_id, verification_id,
                    pre_recovery_status, registered_resume_target_json, recovery_fingerprint,
                    observed_external_state_fingerprint, verification_input_fingerprint,
                    contract_or_checkpoint_fingerprint, last_recheck_input_hash,
                    version, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                _insert_params(context),
            )
        else:
            current_version = int(existing["version"])
            if current_version != context["version"] - 1:
                raise RecoveryConflictError(
                    f"RecoveryContext version conflict for run {context['run_id']}"
                )
            cursor = self._connection.execute(
                """
                UPDATE recovery_contexts SET
                    reason = ?, scope = ?, action_id = ?, execution_attempt_id = ?,
                    verification_id = ?, pre_recovery_status = ?,
                    registered_resume_target_json = ?, recovery_fingerprint = ?,
                    observed_external_state_fingerprint = ?, verification_input_fingerprint = ?,
                    contract_or_checkpoint_fingerprint = ?, last_recheck_input_hash = ?,
                    version = ?, updated_at_ms = ?
                WHERE run_id = ? AND version = ?;
                """,
                (
                    context["reason"],
                    context["scope"],
                    context.get("action_id"),
                    context.get("execution_attempt_id"),
                    context.get("verification_id"),
                    context["pre_recovery_status"],
                    _resume_target_json(context.get("registered_resume_target")),
                    context["recovery_fingerprint"],
                    context.get("observed_external_state_fingerprint"),
                    context.get("verification_input_fingerprint"),
                    context.get("contract_or_checkpoint_fingerprint"),
                    context.get("last_recheck_input_hash"),
                    context["version"],
                    context["updated_at_ms"],
                    context["run_id"],
                    current_version,
                ),
            )
            if cursor.rowcount != 1:
                raise RecoveryConflictError(
                    f"RecoveryContext version conflict for run {context['run_id']}"
                )
        return self._required(context["run_id"])

    def load_current_context(self, run_id: str) -> RecoveryContextV1 | None:
        row = self._connection.execute(
            "SELECT * FROM recovery_contexts WHERE run_id = ?;", (run_id,)
        ).fetchone()
        return None if row is None else _to_context(row)

    def clear_context(self, run_id: str, expected_version: int) -> None:
        cursor = self._connection.execute(
            "DELETE FROM recovery_contexts WHERE run_id = ? AND version = ?;",
            (run_id, expected_version),
        )
        if cursor.rowcount != 1:
            raise RecoveryConflictError(f"RecoveryContext clear conflict for run {run_id}")
        self._connection.execute(
            """
            INSERT INTO recovery_context_tombstones (run_id, last_version, cleared_at_ms)
            VALUES (?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                last_version = excluded.last_version,
                cleared_at_ms = excluded.cleared_at_ms
            WHERE recovery_context_tombstones.last_version < excluded.last_version;
            """,
            (run_id, expected_version, self._now_ms()),
        )

    def list_candidates_bounded(self, limit: int) -> list[RecoveryContextV1]:
        if limit < 1 or limit > 1000:
            raise ValueError("RecoveryContext candidate limit must be between 1 and 1000")
        rows = self._connection.execute(
            "SELECT * FROM recovery_contexts ORDER BY created_at_ms, run_id LIMIT ?;",
            (limit,),
        ).fetchall()
        return [_to_context(row) for row in rows]

    def _required(self, run_id: str) -> RecoveryContextV1:
        context = self.load_current_context(run_id)
        if context is None:
            raise LookupError(f"recovery context not found after write: {run_id}")
        return context


def _resume_target_json(value: object | None) -> str | None:
    if value is None:
        return None
    return dumps(asdict(cast(Any, value)), sort_keys=True, separators=(",", ":"))


def _insert_params(context: RecoveryContextV1) -> tuple[object, ...]:
    return (
        context["run_id"],
        context["reason"],
        context["scope"],
        context.get("action_id"),
        context.get("execution_attempt_id"),
        context.get("verification_id"),
        context["pre_recovery_status"],
        _resume_target_json(context.get("registered_resume_target")),
        context["recovery_fingerprint"],
        context.get("observed_external_state_fingerprint"),
        context.get("verification_input_fingerprint"),
        context.get("contract_or_checkpoint_fingerprint"),
        context.get("last_recheck_input_hash"),
        context["version"],
        context["created_at_ms"],
        context["updated_at_ms"],
    )


def _to_context(row: sqlite3.Row) -> RecoveryContextV1:
    resume_target_json = row["registered_resume_target_json"]
    resume_target = (
        None if resume_target_json is None else deserialize_resume_target(loads(resume_target_json))
    )
    context: RecoveryContextV1 = {
        "schema_version": 1,
        "run_id": str(row["run_id"]),
        "reason": cast(str, row["reason"]),  # type: ignore[typeddict-item]
        "scope": cast(str, row["scope"]),  # type: ignore[typeddict-item]
        "pre_recovery_status": str(row["pre_recovery_status"]),
        "recovery_fingerprint": str(row["recovery_fingerprint"]),
        "version": int(row["version"]),
        "created_at_ms": int(row["created_at_ms"]),
        "updated_at_ms": int(row["updated_at_ms"]),
    }
    if row["action_id"] is not None:
        context["action_id"] = str(row["action_id"])
    if row["execution_attempt_id"] is not None:
        context["execution_attempt_id"] = str(row["execution_attempt_id"])
    if row["verification_id"] is not None:
        context["verification_id"] = str(row["verification_id"])
    if resume_target is not None:
        context["registered_resume_target"] = resume_target
    if row["observed_external_state_fingerprint"] is not None:
        context["observed_external_state_fingerprint"] = str(
            row["observed_external_state_fingerprint"]
        )
    if row["verification_input_fingerprint"] is not None:
        context["verification_input_fingerprint"] = str(row["verification_input_fingerprint"])
    if row["contract_or_checkpoint_fingerprint"] is not None:
        context["contract_or_checkpoint_fingerprint"] = str(
            row["contract_or_checkpoint_fingerprint"]
        )
    if row["last_recheck_input_hash"] is not None:
        context["last_recheck_input_hash"] = str(row["last_recheck_input_hash"])
    return context
