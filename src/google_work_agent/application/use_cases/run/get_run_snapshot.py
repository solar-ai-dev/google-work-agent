"""Get one canonical persisted run snapshot."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Row

from google_work_agent.domain import (
    ActionCommand, ActionStatus, EffectType, RunStatus,
    next_allowed_action_commands, next_allowed_run_commands, parse_action_risk_json,
)
from google_work_agent.ports import QueryConnectionFactory


@dataclass(frozen=True, slots=True)
class ActionSnapshotResult:
    action_id: str
    tool_name: str
    status: str
    version: int
    effect_type: str
    approval_required: bool
    verification_policy: str
    risk: dict[str, object]
    next_allowed_commands: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GetRunSnapshotQuery:
    run_id: str


@dataclass(frozen=True, slots=True)
class GetRunSnapshotResult:
    run_id: str
    conversation_id: str
    status: str
    version: int
    entry_mode: str
    requested_mode: str
    actual_runtime: str | None
    started_at_ms: int
    finished_at_ms: int | None
    active_plan: dict[str, object] | None
    actions: tuple[ActionSnapshotResult, ...]
    approvals: tuple[dict[str, object], ...]
    execution_status: dict[str, object]
    verification_summary: dict[str, object]
    recovery_summary: dict[str, object]
    result_kind: str | None
    next_allowed_commands: tuple[str, ...]
    snapshot_version: int


class GetRunSnapshotHandler:
    def __init__(self, *, database_path: Path, connection_factory: QueryConnectionFactory) -> None:
        self._database_path = database_path
        self._connection_factory = connection_factory

    @classmethod
    def from_legacy_query_supplier(cls, query_supplier: Callable[[], object]) -> "GetRunSnapshotHandler":
        query = query_supplier()
        return cls(database_path=query._database_path, connection_factory=query._connection_factory)  # type: ignore[attr-defined]

    def __call__(self, query: GetRunSnapshotQuery) -> GetRunSnapshotResult | None:
        with self._connection_factory(self._database_path) as connection:
            run_row = connection.execute(
                "SELECT id, conversation_id, entry_mode, status, requested_mode, actual_runtime, version, started_at_ms, finished_at_ms FROM runs WHERE id = ?;",
                (query.run_id,),
            ).fetchone()
            if run_row is None:
                return None
            plan_row = connection.execute(
                "SELECT id, revision_no, status, summary_text, created_at_ms, review_status FROM plans WHERE run_id = ? ORDER BY revision_no DESC, id DESC LIMIT 1;",
                (query.run_id,),
            ).fetchone()
            actions: tuple[ActionSnapshotResult, ...] = ()
            approvals: tuple[dict[str, object], ...] = ()
            verification_summary = {"verified_count": 0, "mismatch_count": 0}
            recovery_count = 0
            if plan_row is not None:
                action_rows = connection.execute(
                    "SELECT id, tool_name, status, version, effect_type, approval_requirement, verification_policy, risk_json FROM actions WHERE plan_id = ? ORDER BY position ASC, id ASC;",
                    (str(plan_row["id"]),),
                ).fetchall()
                actions = tuple(_action_snapshot(row, approval_allowed=str(plan_row["review_status"]) == "PASSED") for row in action_rows)
                recovery_count = sum(action.status == ActionStatus.UNKNOWN_RESULT.value for action in actions)
                approvals = tuple(
                    {"approval_id": str(row["id"]), "action_id": str(row["action_id"]), "status": str(row["status"]), "approved_at_ms": int(row["approved_at_ms"]), "expires_at_ms": int(row["expires_at_ms"])}
                    for row in connection.execute(
                        "SELECT id, action_id, status, approved_at_ms, expires_at_ms FROM approvals WHERE action_id IN (SELECT id FROM actions WHERE plan_id = ?) ORDER BY approved_at_ms DESC, id DESC;",
                        (str(plan_row["id"]),),
                    ).fetchall()
                )
                verification_rows = connection.execute(
                    "SELECT status, COUNT(*) AS total FROM verifications WHERE execution_attempt_id IN (SELECT id FROM execution_attempts WHERE approval_id IN (SELECT id FROM approvals WHERE action_id IN (SELECT id FROM actions WHERE plan_id = ?))) GROUP BY status;",
                    (str(plan_row["id"]),),
                ).fetchall()
                verification_summary = {
                    "verified_count": sum(int(row["total"]) for row in verification_rows if str(row["status"]) == "VERIFIED"),
                    "mismatch_count": sum(int(row["total"]) for row in verification_rows if str(row["status"]) == "MISMATCH"),
                }
        run_status = RunStatus(str(run_row["status"]))
        active_plan = None
        if plan_row is not None:
            active_plan = {
                "plan_id": str(plan_row["id"]), "revision_no": int(plan_row["revision_no"]), "status": str(plan_row["status"]),
                "summary_text": None if plan_row["summary_text"] is None else str(plan_row["summary_text"]),
                "created_at_ms": int(plan_row["created_at_ms"]),
            }
        return GetRunSnapshotResult(
            run_id=str(run_row["id"]), conversation_id=str(run_row["conversation_id"]), status=run_status.value,
            version=int(run_row["version"]), entry_mode=str(run_row["entry_mode"]), requested_mode=str(run_row["requested_mode"]),
            actual_runtime=None if run_row["actual_runtime"] is None else str(run_row["actual_runtime"]), started_at_ms=int(run_row["started_at_ms"]),
            finished_at_ms=None if run_row["finished_at_ms"] is None else int(run_row["finished_at_ms"]), active_plan=active_plan, actions=actions,
            approvals=approvals,
            execution_status={"action_count": len(actions), "terminal_action_count": sum(action.status in {ActionStatus.VERIFIED.value, ActionStatus.REJECTED.value, ActionStatus.FAILED.value, ActionStatus.MISMATCH.value, ActionStatus.BLOCKED.value, ActionStatus.DEPENDENCY_BLOCKED.value, ActionStatus.CANCELLED.value} for action in actions)},
            verification_summary=verification_summary, recovery_summary={"unknown_result_action_count": recovery_count},
            result_kind=_cancel_result_kind(run_status=run_status, actions=actions),
            next_allowed_commands=tuple(item.value for item in next_allowed_run_commands(run_status)), snapshot_version=1,
        )


def _action_snapshot(row: Row, *, approval_allowed: bool) -> ActionSnapshotResult:
    status = ActionStatus(str(row["status"]))
    effect_type = EffectType(str(row["effect_type"]))
    return ActionSnapshotResult(
        action_id=str(row["id"]), tool_name=str(row["tool_name"]), status=status.value, version=int(row["version"]), effect_type=effect_type.value,
        approval_required=str(row["approval_requirement"]) == "REQUIRED", verification_policy=str(row["verification_policy"]), risk=parse_action_risk_json(str(row["risk_json"])),
        next_allowed_commands=tuple(item.value for item in next_allowed_action_commands(status, effect_type=effect_type) if approval_allowed or item is not ActionCommand.APPROVE_ACTION),
    )


def _cancel_result_kind(*, run_status: RunStatus, actions: tuple[ActionSnapshotResult, ...]) -> str | None:
    if run_status is not RunStatus.CANCELLED:
        return None
    has_success = any(action.status == ActionStatus.VERIFIED.value for action in actions)
    has_cancelled = any(action.status == ActionStatus.CANCELLED.value for action in actions)
    return "PARTIAL" if has_success and has_cancelled else "CANCELLED"
