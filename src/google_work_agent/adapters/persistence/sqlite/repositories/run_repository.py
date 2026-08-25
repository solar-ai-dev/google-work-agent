"""SQLite run repository with canonical lifecycle persistence."""
import sqlite3

from google_work_agent.domain import (
    CommandResult,
    ResultCode,
    RunCommand,
    RunStatus,
    next_allowed_run_commands,
    transition_run,
)
from google_work_agent.domain.confirmation import (
    resume_confirmation as transition_resume_confirmation,
)
from google_work_agent.domain.run.model import RunTransitionRejected
from google_work_agent.domain.run.transitions.resume_after_reauth import (
    transition_resume_after_reauth,
)
from google_work_agent.ports.models import RunCreateRecord, RunRecord


class SQLiteRunRepository:
    def __init__(self, connection: sqlite3.Connection) -> None: self._connection=connection

    # --- STR-149 canonical surface (run.start_run / CAP-APP-005) ---
    def get(self, run_id: str) -> RunRecord | None:
        r=self._connection.execute("SELECT id, conversation_id, status, version, started_at_ms, finished_at_ms FROM runs WHERE id=?;", (run_id,)).fetchone()
        return None if r is None else RunRecord(id=str(r["id"]), conversation_id=str(r["conversation_id"]), status=RunStatus(str(r["status"])), version=int(r["version"]), started_at_ms=int(r["started_at_ms"]), finished_at_ms=None if r["finished_at_ms"] is None else int(r["finished_at_ms"]))

    def get_snapshot(self, run_id: str) -> RunRecord | None:
        return self.get(run_id)

    def find_open_by_conversation(self, conversation_id: str) -> RunRecord | None:
        r=self._connection.execute("SELECT id, conversation_id, status, version, started_at_ms, finished_at_ms FROM runs WHERE conversation_id=? AND finished_at_ms IS NULL ORDER BY started_at_ms DESC LIMIT 1;", (conversation_id,)).fetchone()
        return None if r is None else RunRecord(id=str(r["id"]), conversation_id=str(r["conversation_id"]), status=RunStatus(str(r["status"])), version=int(r["version"]), started_at_ms=int(r["started_at_ms"]), finished_at_ms=None)

    def create(self, run: RunCreateRecord) -> None:
        self._connection.execute("INSERT INTO runs (id, conversation_id, entry_mode, status, langgraph_thread_id, requested_mode, actual_runtime, budget_json, version, started_at_ms, finished_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);", (run.id,run.conversation_id,run.entry_mode,run.status.value,run.langgraph_thread_id,run.requested_mode,run.actual_runtime,run.budget_json,run.version,run.started_at_ms,run.finished_at_ms))

    def update_if_version_and_status(
        self,
        run_id: str,
        expected_version: int,
        expected_statuses: frozenset[RunStatus],
        values: dict[str, object],
    ) -> bool:
        if not values:
            raise ValueError("update_if_version_and_status requires at least one value")
        if not expected_statuses:
            raise ValueError("update_if_version_and_status requires at least one expected status")
        set_clause = ", ".join(f"{column} = ?" for column in values)
        status_placeholders = ", ".join("?" for _ in expected_statuses)
        params = [
            *values.values(),
            run_id,
            expected_version,
            *(status.value for status in expected_statuses),
        ]
        cursor = self._connection.execute(
            f"UPDATE runs SET {set_clause} WHERE id = ? AND version = ? AND status IN ({status_placeholders});",
            params,
        )
        return cursor.rowcount == 1

    # --- pre-existing shim kept for non-StartRun Run lifecycle capabilities.
    # `get_by_id` is the same read surface under a legacy name; the ~20
    # domain-transition methods below own deciding the next status/version via
    # `transition_run` and friends, then delegate the actual row write to
    # `update_if_version_and_status` above through `_apply`. See
    # ports/persistence/run_repository.py for the canonical-vs-shim boundary
    # this file implements. `add`/`get_open_by_conversation` had zero
    # remaining callers (#72 final cleanup) and were removed.
    def get_by_id(self, run_id: str) -> RunRecord | None: return self.get(run_id)
    def _apply(self, *, run_id: str, previous_status: RunStatus, previous_version: int, result: CommandResult[RunStatus, RunCommand], finished_at_ms: int | None, error_message: str) -> CommandResult[RunStatus, RunCommand]:
        if not result.applied: return result
        applied = self.update_if_version_and_status(
            run_id,
            previous_version,
            frozenset({previous_status}),
            {"status": result.current_status.value, "version": result.current_version, "finished_at_ms": finished_at_ms},
        )
        if not applied: raise sqlite3.IntegrityError(error_message)
        return result
    def _transition(self, run_id: str, *, expected_version: int, command: RunCommand, finished_at_ms: int | None = None, plan_requires_approval: bool | None = None, recovery_next_status: RunStatus | None = None) -> CommandResult[RunStatus, RunCommand]:
        cur=self.get_by_id(run_id)
        if cur is None: raise LookupError(f"run not found: {run_id}")
        kwargs={}
        if plan_requires_approval is not None: kwargs["plan_requires_approval"]=plan_requires_approval
        if recovery_next_status is not None: kwargs["recovery_next_status"]=recovery_next_status
        result=transition_run(cur.status, command=command, current_version=cur.version, expected_version=expected_version, **kwargs)
        return self._apply(run_id=run_id, previous_status=cur.status, previous_version=cur.version, result=result, finished_at_ms=finished_at_ms, error_message=f"run {command.value} affected an unexpected row count")
    def start_analysis(self, run_id: str, *, expected_version: int, finished_at_ms: int | None=None): return self._transition(run_id, expected_version=expected_version, command=RunCommand.START_ANALYSIS, finished_at_ms=finished_at_ms)
    def begin_retrieval(self, run_id: str, *, expected_version: int, finished_at_ms: int | None=None): return self._transition(run_id, expected_version=expected_version, command=RunCommand.BEGIN_RETRIEVAL, finished_at_ms=finished_at_ms)
    def begin_planning(self, run_id: str, *, expected_version: int, finished_at_ms: int | None=None): return self._transition(run_id, expected_version=expected_version, command=RunCommand.BEGIN_PLANNING, finished_at_ms=finished_at_ms)
    def replan(self, run_id: str, *, expected_version: int, finished_at_ms: int | None=None): return self._transition(run_id, expected_version=expected_version, command=RunCommand.REPLAN, finished_at_ms=finished_at_ms)
    def request_confirmation(self, run_id: str, *, expected_version: int, finished_at_ms: int | None=None): return self._transition(run_id, expected_version=expected_version, command=RunCommand.REQUEST_CONFIRMATION, finished_at_ms=finished_at_ms)
    def resume_confirmation(self, run_id: str, *, expected_version: int, resume_status: RunStatus, finished_at_ms: int | None=None) -> CommandResult[RunStatus, RunCommand]:
        cur=self.get_by_id(run_id)
        if cur is None: raise LookupError(f"run not found: {run_id}")
        result=transition_resume_confirmation(cur.status, current_version=cur.version, expected_version=expected_version, resume_status=resume_status)
        return self._apply(run_id=run_id, previous_status=cur.status, previous_version=cur.version, result=result, finished_at_ms=finished_at_ms, error_message="run resume-confirmation affected an unexpected row count")
    def resume_after_reauth(self, run_id: str, *, expected_version: int, resume_status: RunStatus, finished_at_ms: int | None=None) -> CommandResult[RunStatus, RunCommand]:
        cur=self.get_by_id(run_id)
        if cur is None: raise LookupError(f"run not found: {run_id}")
        if cur.version != expected_version:
            result=CommandResult(False,ResultCode.VERSION_CONFLICT,cur.status,cur.version,next_allowed_run_commands(cur.status),"expected_version does not match current_version")
        else:
            try: next_status=transition_resume_after_reauth(cur.status,resume_status=resume_status)
            except RunTransitionRejected as error:
                result=CommandResult(False,ResultCode.STATE_CONFLICT,cur.status,cur.version,next_allowed_run_commands(cur.status),str(error))
            else:
                result=CommandResult(True,ResultCode.TRANSITION_APPLIED,next_status,cur.version+1,next_allowed_run_commands(next_status),None)
        return self._apply(run_id=run_id,previous_status=cur.status,previous_version=cur.version,result=result,finished_at_ms=finished_at_ms,error_message="run resume-after-reauth affected an unexpected row count")
    def complete_answer_only_run(self, run_id: str, *, expected_version: int, finished_at_ms: int): return self._transition(run_id, expected_version=expected_version, command=RunCommand.COMPLETE_ANSWER_ONLY_RUN, finished_at_ms=finished_at_ms)
    def complete_write_run(self, run_id: str, *, expected_version: int, finished_at_ms: int): return self._transition(run_id, expected_version=expected_version, command=RunCommand.COMPLETE_WRITE_RUN, finished_at_ms=finished_at_ms)
    def finalize_action_outcomes(self, run_id: str, *, expected_version: int, finished_at_ms: int): return self._transition(run_id, expected_version=expected_version, command=RunCommand.FINALIZE_ACTION_OUTCOMES, finished_at_ms=finished_at_ms)
    def block_run(self, run_id: str, *, expected_version: int, finished_at_ms: int): return self._transition(run_id, expected_version=expected_version, command=RunCommand.BLOCK_RUN, finished_at_ms=finished_at_ms)
    def fail_run(self, run_id: str, *, expected_version: int, finished_at_ms: int): return self._transition(run_id, expected_version=expected_version, command=RunCommand.FAIL_RUN, finished_at_ms=finished_at_ms)
    def publish_read_only_plan(self, run_id: str, *, expected_version: int, finished_at_ms: int | None=None): return self._transition(run_id, expected_version=expected_version, command=RunCommand.PUBLISH_PLAN, finished_at_ms=finished_at_ms, plan_requires_approval=False)
    def publish_write_plan(self, run_id: str, *, expected_version: int, finished_at_ms: int | None=None): return self._transition(run_id, expected_version=expected_version, command=RunCommand.PUBLISH_PLAN, finished_at_ms=finished_at_ms, plan_requires_approval=True)
    def request_cancel(self, run_id: str, *, expected_version: int): return self._transition(run_id, expected_version=expected_version, command=RunCommand.REQUEST_CANCEL)
    def finalize_cancel(self, run_id: str, *, expected_version: int, finished_at_ms: int): return self._transition(run_id, expected_version=expected_version, command=RunCommand.FINALIZE_CANCEL, finished_at_ms=finished_at_ms)
    def require_reauth(self, run_id: str, *, expected_version: int, finished_at_ms: int | None=None): return self._transition(run_id, expected_version=expected_version, command=RunCommand.REQUIRE_REAUTH, finished_at_ms=finished_at_ms)
    def require_recovery(self, run_id: str, *, expected_version: int, finished_at_ms: int | None=None): return self._transition(run_id, expected_version=expected_version, command=RunCommand.REQUIRE_RECOVERY, finished_at_ms=finished_at_ms)
    def resolve_recovery(self, run_id: str, *, expected_version: int, recovery_next_status: RunStatus, finished_at_ms: int | None=None): return self._transition(run_id, expected_version=expected_version, command=RunCommand.RESOLVE_RECOVERY, finished_at_ms=finished_at_ms, recovery_next_status=recovery_next_status)
    def complete_read_only_run(self, run_id: str, *, expected_version: int, finished_at_ms: int) -> CommandResult[RunStatus, RunCommand]:
        cur=self.get_by_id(run_id)
        if cur is None: raise LookupError(f"run not found: {run_id}")
        applied=cur.version==expected_version and cur.status is RunStatus.EXECUTING
        result=CommandResult(applied=applied, result_code=ResultCode.TRANSITION_APPLIED if applied else (ResultCode.VERSION_CONFLICT if cur.version!=expected_version else ResultCode.STATE_CONFLICT), current_status=RunStatus.COMPLETED if applied else cur.status, current_version=cur.version+1 if applied else cur.version, next_allowed_commands=(), conflict_detail=None if applied else ("expected_version does not match current_version" if cur.version!=expected_version else "read-only run completion requires EXECUTING status"))
        return self._apply(run_id=run_id, previous_status=cur.status, previous_version=cur.version, result=result, finished_at_ms=finished_at_ms, error_message="read-only run completion affected an unexpected row count")
    def set_recovery_required(self, run_id: str, *, finished_at_ms: int | None=None) -> RunRecord:
        cur=self.get_by_id(run_id)
        if cur is None: raise LookupError(f"run not found: {run_id}")
        if cur.status is not RunStatus.RECOVERY_REQUIRED:
            result=self.require_recovery(run_id, expected_version=cur.version, finished_at_ms=finished_at_ms)
            if not result.applied: raise sqlite3.IntegrityError(f"run require-recovery failed: {result.conflict_detail}")
        updated=self.get_by_id(run_id)
        if updated is None: raise LookupError(f"run not found after recovery update: {run_id}")
        return updated
    def set_reauth_required(self, run_id: str, *, finished_at_ms: int | None=None) -> RunRecord:
        cur=self.get_by_id(run_id)
        if cur is None: raise LookupError(f"run not found: {run_id}")
        result=self.require_reauth(run_id, expected_version=cur.version, finished_at_ms=finished_at_ms)
        if not result.applied: raise sqlite3.IntegrityError(f"run require-reauth failed: {result.conflict_detail}")
        updated=self.get_by_id(run_id)
        if updated is None: raise LookupError(f"run not found after reauth update: {run_id}")
        return updated
    def set_verifying(self, run_id: str, *, finished_at_ms: int | None=None) -> RunRecord:
        cur=self.get_by_id(run_id)
        if cur is None: raise LookupError(f"run not found: {run_id}")
        result=self.resolve_recovery(run_id, expected_version=cur.version, recovery_next_status=RunStatus.VERIFYING, finished_at_ms=finished_at_ms) if cur.status is RunStatus.RECOVERY_REQUIRED else self._transition(run_id, expected_version=cur.version, command=RunCommand.BEGIN_VERIFICATION, finished_at_ms=finished_at_ms)
        if not result.applied: raise sqlite3.IntegrityError(f"run set-verifying failed: {result.conflict_detail}")
        updated=self.get_by_id(run_id)
        if updated is None: raise LookupError(f"run not found after verification transition: {run_id}")
        return updated
