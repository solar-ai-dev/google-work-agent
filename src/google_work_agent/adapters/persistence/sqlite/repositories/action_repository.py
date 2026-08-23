"""SQLite action repository with connector-aware identity."""
import sqlite3

from google_work_agent.domain import (
    ActionCommand,
    ActionStatus,
    CommandResult,
    EffectType,
    VerificationStatus,
    canonicalize_action_risk,
    parse_action_risk_json,
    transition_action,
)
from google_work_agent.ports.models import ActionRecord

class SQLiteActionRepository:
    _SELECT="SELECT id, plan_id, connector_id, position, tool_name, effect_type, approval_requirement, verification_policy, recovery_policy, target_resource_ref_id, status, arguments_json, arguments_hash, expected_json, risk_json, version, created_at_ms, updated_at_ms FROM actions"
    def __init__(self, connection: sqlite3.Connection) -> None: self._connection=connection
    @staticmethod
    def _record(r: sqlite3.Row) -> ActionRecord:
        risk=parse_action_risk_json(str(r["risk_json"]))
        return ActionRecord(id=str(r["id"]), plan_id=str(r["plan_id"]), connector_id=str(r["connector_id"]), position=int(r["position"]), tool_name=str(r["tool_name"]), effect_type=str(r["effect_type"]), approval_requirement=str(r["approval_requirement"]), verification_policy=str(r["verification_policy"]), recovery_policy=str(r["recovery_policy"]), target_resource_ref_id=None if r["target_resource_ref_id"] is None else str(r["target_resource_ref_id"]), status=str(r["status"]), arguments_json=str(r["arguments_json"]), arguments_hash=str(r["arguments_hash"]), expected_json=str(r["expected_json"]), risk=risk, version=int(r["version"]), created_at_ms=int(r["created_at_ms"]), updated_at_ms=int(r["updated_at_ms"]))
    def get_by_id(self, action_id: str) -> ActionRecord | None:
        r=self._connection.execute(self._SELECT+" WHERE id=?;", (action_id,)).fetchone(); return None if r is None else self._record(r)
    def _insert(self, action: ActionRecord) -> None:
        if not action.connector_id: raise ValueError("action persistence requires connector_id")
        self._connection.execute("INSERT INTO actions (id, plan_id, position, tool_name, effect_type, approval_requirement, verification_policy, recovery_policy, target_resource_ref_id, status, arguments_json, arguments_hash, expected_json, risk_json, version, created_at_ms, updated_at_ms, connector_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);", (action.id,action.plan_id,action.position,action.tool_name,action.effect_type,action.approval_requirement,action.verification_policy,action.recovery_policy,action.target_resource_ref_id,action.status,action.arguments_json,action.arguments_hash,action.expected_json,canonicalize_action_risk(action.risk),action.version,action.created_at_ms,action.updated_at_ms,action.connector_id))
    def insert_read_action(self, action: ActionRecord) -> None: self._insert(action)
    def insert_write_action(self, action: ActionRecord) -> None: self._insert(action)
    def _transition(self, action_id: str, *, command: ActionCommand, expected_version: int, updated_at_ms: int, verification_status: VerificationStatus | None=None, result_not_executed_confirmed: bool=False) -> CommandResult[ActionStatus, ActionCommand]:
        cur=self.get_by_id(action_id)
        if cur is None: raise LookupError(f"action not found: {action_id}")
        result=transition_action(ActionStatus(cur.status), command=command, current_version=cur.version, expected_version=expected_version, effect_type=EffectType(cur.effect_type), verification_status=verification_status, result_not_executed_confirmed=result_not_executed_confirmed)
        if not result.applied: return result
        c=self._connection.execute("UPDATE actions SET status=?, version=?, updated_at_ms=? WHERE id=? AND version=?;", (result.current_status.value,result.current_version,updated_at_ms,action_id,cur.version))
        if c.rowcount != 1: raise sqlite3.IntegrityError("action transition affected an unexpected row count")
        return result
    def claim_read(self, action_id: str, *, expected_version: int, updated_at_ms: int): return self._transition(action_id,command=ActionCommand.CLAIM_READ_ACTION,expected_version=expected_version,updated_at_ms=updated_at_ms)
    def complete_read(self, action_id: str, *, expected_version: int, updated_at_ms: int): return self._transition(action_id,command=ActionCommand.COMPLETE_READ_ACTION,expected_version=expected_version,updated_at_ms=updated_at_ms)
    def finalize_read(self, action_id: str, *, expected_version: int, updated_at_ms: int): return self._transition(action_id,command=ActionCommand.FINALIZE_READ_ACTION,expected_version=expected_version,updated_at_ms=updated_at_ms)
    def fail_read(self, action_id: str, *, expected_version: int, updated_at_ms: int): return self._transition(action_id,command=ActionCommand.FAIL_READ_ACTION,expected_version=expected_version,updated_at_ms=updated_at_ms)
    def approve_write(self, action_id: str, *, expected_version: int, updated_at_ms: int): return self._transition(action_id,command=ActionCommand.APPROVE_ACTION,expected_version=expected_version,updated_at_ms=updated_at_ms)
    def reject_write(self, action_id: str, *, expected_version: int, updated_at_ms: int): return self._transition(action_id,command=ActionCommand.REJECT_ACTION,expected_version=expected_version,updated_at_ms=updated_at_ms)
    def claim_execution(self, action_id: str, *, expected_version: int, updated_at_ms: int): return self._transition(action_id,command=ActionCommand.CLAIM_EXECUTION,expected_version=expected_version,updated_at_ms=updated_at_ms)
    def store_success(self, action_id: str, *, expected_version: int, updated_at_ms: int): return self._transition(action_id,command=ActionCommand.STORE_SUCCESS,expected_version=expected_version,updated_at_ms=updated_at_ms)
    def mark_failed(self, action_id: str, *, expected_version: int, updated_at_ms: int): return self._transition(action_id,command=ActionCommand.MARK_FAILED,expected_version=expected_version,updated_at_ms=updated_at_ms)
    def mark_unknown_result(self, action_id: str, *, expected_version: int, updated_at_ms: int): return self._transition(action_id,command=ActionCommand.MARK_UNKNOWN_RESULT,expected_version=expected_version,updated_at_ms=updated_at_ms)
    def recover_existing_result(self, action_id: str, *, expected_version: int, updated_at_ms: int): return self._transition(action_id,command=ActionCommand.RECOVER_EXISTING_RESULT,expected_version=expected_version,updated_at_ms=updated_at_ms)
    def resolve_unknown_as_failed(self, action_id: str, *, expected_version: int, updated_at_ms: int): return self._transition(action_id,command=ActionCommand.RESOLVE_AS_FAILED,expected_version=expected_version,updated_at_ms=updated_at_ms,result_not_executed_confirmed=True)
    def prepare_write_retry(self, action_id: str, *, expected_version: int, updated_at_ms: int): return self._transition(action_id,command=ActionCommand.PREPARE_WRITE_RETRY,expected_version=expected_version,updated_at_ms=updated_at_ms)
    def cancel_pending(self, action_id: str, *, expected_version: int, updated_at_ms: int): return self._transition(action_id,command=ActionCommand.CANCEL_PENDING_ACTION,expected_version=expected_version,updated_at_ms=updated_at_ms)
    def store_verification(self, action_id: str, *, expected_version: int, updated_at_ms: int, verification_status: str): return self._transition(action_id,command=ActionCommand.STORE_VERIFICATION,expected_version=expected_version,updated_at_ms=updated_at_ms,verification_status=VerificationStatus(verification_status))
    def modify_write(self, action_id: str, *, expected_version: int, updated_at_ms: int, arguments_json: str, arguments_hash: str, risk: dict[str, object]) -> CommandResult[ActionStatus, ActionCommand]:
        cur=self.get_by_id(action_id)
        if cur is None: raise LookupError(f"action not found: {action_id}")
        result=transition_action(ActionStatus(cur.status), command=ActionCommand.MODIFY_ACTION, current_version=cur.version, expected_version=expected_version, effect_type=EffectType(cur.effect_type))
        if not result.applied: return result
        c=self._connection.execute("UPDATE actions SET status=?, version=?, updated_at_ms=?, arguments_json=?, arguments_hash=?, risk_json=? WHERE id=? AND version=?;", (result.current_status.value,result.current_version,updated_at_ms,arguments_json,arguments_hash,canonicalize_action_risk(risk),action_id,cur.version))
        if c.rowcount != 1: raise sqlite3.IntegrityError("write action modify transition affected an unexpected row count")
        return result
    def update_risk_snapshot(self, action_id: str, *, expected_version: int, updated_at_ms: int, risk: dict[str, object]) -> None:
        c=self._connection.execute("UPDATE actions SET risk_json=?, updated_at_ms=? WHERE id=? AND version=?;", (canonicalize_action_risk(risk),updated_at_ms,action_id,expected_version))
        if c.rowcount != 1: raise sqlite3.IntegrityError("action risk update affected an unexpected row count")
    def mark_dependency_blocked(self, action_id: str, *, updated_at_ms: int) -> bool:
        c=self._connection.execute("UPDATE actions SET status='DEPENDENCY_BLOCKED', version=version+1, updated_at_ms=? WHERE id=? AND status IN ('PROPOSED','MODIFIED','APPROVED');", (updated_at_ms,action_id))
        if c.rowcount > 1: raise sqlite3.IntegrityError("dependency blocked update affected an unexpected row count")
        return c.rowcount == 1
    def list_by_plan(self, plan_id: str) -> tuple[ActionRecord, ...]:
        return tuple(self._record(r) for r in self._connection.execute(self._SELECT+" WHERE plan_id=? ORDER BY position ASC;", (plan_id,)).fetchall())
    def list_ready_actions(self, plan_id: str) -> tuple[ActionRecord, ...]:
        rows=self._connection.execute(self._SELECT+" AS a WHERE a.plan_id=? AND a.status='PROPOSED' AND NOT EXISTS (SELECT 1 FROM action_dependencies AS d JOIN actions AS dep ON dep.id=d.depends_on_action_id WHERE d.action_id=a.id AND dep.status <> 'VERIFIED') ORDER BY a.position ASC;", (plan_id,)).fetchall(); return tuple(self._record(r) for r in rows)
    def connector_id_for_action(self, action_id: str) -> str:
        action=self.get_by_id(action_id)
        if action is None: raise LookupError(f"action not found: {action_id}")
        return action.connector_id
