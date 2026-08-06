"""SQLite-backed repository implementations for Phase A product core."""

import sqlite3
from json import dumps, loads

from google_work_agent.domain import (
    ActionCommand,
    ActionStatus,
    ApprovalStatus,
    CommandResult,
    EffectType,
    ExecutionAttemptStatus,
    ResultCode,
    RunCommand,
    RunStatus,
    VerificationStatus,
    transition_action,
    transition_run,
)
from google_work_agent.ports import (
    ActionRecord,
    AnswerOnlyResponse,
    ApprovalRecord,
    AuditEventRecord,
    CommandReceiptRecord,
    CommandReceiptStatus,
    ConversationRecord,
    EvidenceOriginType,
    EvidenceRecord,
    ExecutionAttemptRecord,
    MessageRecord,
    PlanRecord,
    PlanStatus,
    ResourceRefRecord,
    ResourceSource,
    RunRecord,
    StoredResourceType,
    TraceEventRecord,
    VerificationRecord,
)


class SQLiteConversationRepository:
    """SQLite conversation repository."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_by_id(self, conversation_id: str) -> ConversationRecord | None:
        row = self._connection.execute(
            """
            SELECT id, account_id, title, created_at_ms, updated_at_ms
            FROM conversations
            WHERE id = ?;
            """,
            (conversation_id,),
        ).fetchone()
        if row is None:
            return None
        return ConversationRecord(
            id=str(row["id"]),
            account_id=str(row["account_id"]),
            title=str(row["title"]),
            created_at_ms=int(row["created_at_ms"]),
            updated_at_ms=int(row["updated_at_ms"]),
        )


class SQLiteRunRepository:
    """SQLite run repository with optimistic state transitions."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_by_id(self, run_id: str) -> RunRecord | None:
        row = self._connection.execute(
            """
            SELECT id, conversation_id, status, version, started_at_ms, finished_at_ms
            FROM runs
            WHERE id = ?;
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return RunRecord(
            id=str(row["id"]),
            conversation_id=str(row["conversation_id"]),
            status=RunStatus(str(row["status"])),
            version=int(row["version"]),
            started_at_ms=int(row["started_at_ms"]),
            finished_at_ms=_int_or_none(row["finished_at_ms"]),
        )

    def complete_answer_only_run(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int,
    ) -> CommandResult[RunStatus, RunCommand]:
        current = self.get_by_id(run_id)
        if current is None:
            raise LookupError(f"run not found: {run_id}")

        result = transition_run(
            current.status,
            command=RunCommand.COMPLETE_ANSWER_ONLY_RUN,
            current_version=current.version,
            expected_version=expected_version,
        )
        if not result.applied:
            return result

        cursor = self._connection.execute(
            """
            UPDATE runs
            SET status = ?, version = ?, finished_at_ms = ?
            WHERE id = ? AND version = ?;
            """,
            (
                result.current_status.value,
                result.current_version,
                finished_at_ms,
                run_id,
                current.version,
            ),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError("answer-only run update affected an unexpected row count")
        return result

    def publish_read_only_plan(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int | None = None,
    ) -> CommandResult[RunStatus, RunCommand]:
        current = self.get_by_id(run_id)
        if current is None:
            raise LookupError(f"run not found: {run_id}")

        result = transition_run(
            current.status,
            command=RunCommand.PUBLISH_PLAN,
            current_version=current.version,
            expected_version=expected_version,
            plan_requires_approval=False,
        )
        if not result.applied:
            return result

        cursor = self._connection.execute(
            """
            UPDATE runs
            SET status = ?, version = ?, finished_at_ms = ?
            WHERE id = ? AND version = ?;
            """,
            (
                result.current_status.value,
                result.current_version,
                finished_at_ms,
                run_id,
                current.version,
            ),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError("read-only run publish affected an unexpected row count")
        return result

    def complete_read_only_run(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int,
    ) -> CommandResult[RunStatus, RunCommand]:
        current = self.get_by_id(run_id)
        if current is None:
            raise LookupError(f"run not found: {run_id}")
        result: CommandResult[RunStatus, RunCommand] = CommandResult(
            applied=current.version == expected_version and current.status is RunStatus.EXECUTING,
            result_code=(
                ResultCode.TRANSITION_APPLIED
                if current.version == expected_version and current.status is RunStatus.EXECUTING
                else (
                    ResultCode.VERSION_CONFLICT
                    if current.version != expected_version
                    else ResultCode.STATE_CONFLICT
                )
            ),
            current_status=(
                RunStatus.COMPLETED
                if current.version == expected_version and current.status is RunStatus.EXECUTING
                else current.status
            ),
            current_version=(
                current.version + 1
                if current.version == expected_version and current.status is RunStatus.EXECUTING
                else current.version
            ),
            next_allowed_commands=(),
            conflict_detail=(
                None
                if current.version == expected_version and current.status is RunStatus.EXECUTING
                else (
                    "expected_version does not match current_version"
                    if current.version != expected_version
                    else "read-only run completion requires EXECUTING status"
                )
            ),
        )
        if not result.applied:
            return result

        cursor = self._connection.execute(
            """
            UPDATE runs
            SET status = 'COMPLETED', version = ?, finished_at_ms = ?
            WHERE id = ? AND version = ? AND status = 'EXECUTING';
            """,
            (result.current_version, finished_at_ms, run_id, current.version),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError(
                "read-only run completion affected an unexpected row count"
            )
        return result

    def publish_write_plan(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int | None = None,
    ) -> CommandResult[RunStatus, RunCommand]:
        current = self.get_by_id(run_id)
        if current is None:
            raise LookupError(f"run not found: {run_id}")

        result = transition_run(
            current.status,
            command=RunCommand.PUBLISH_PLAN,
            current_version=current.version,
            expected_version=expected_version,
            plan_requires_approval=True,
        )
        if not result.applied:
            return result

        cursor = self._connection.execute(
            """
            UPDATE runs
            SET status = ?, version = ?, finished_at_ms = ?
            WHERE id = ? AND version = ?;
            """,
            (
                result.current_status.value,
                result.current_version,
                finished_at_ms,
                run_id,
                current.version,
            ),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError("write-plan publish affected an unexpected row count")
        return result

    def request_cancel(
        self,
        run_id: str,
        *,
        expected_version: int,
    ) -> CommandResult[RunStatus, RunCommand]:
        current = self.get_by_id(run_id)
        if current is None:
            raise LookupError(f"run not found: {run_id}")
        result = transition_run(
            current.status,
            command=RunCommand.REQUEST_CANCEL,
            current_version=current.version,
            expected_version=expected_version,
        )
        if not result.applied:
            return result
        cursor = self._connection.execute(
            """
            UPDATE runs
            SET status = ?, version = ?
            WHERE id = ? AND version = ?;
            """,
            (result.current_status.value, result.current_version, run_id, current.version),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError("run cancel request affected an unexpected row count")
        return result

    def finalize_cancel(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int,
    ) -> CommandResult[RunStatus, RunCommand]:
        current = self.get_by_id(run_id)
        if current is None:
            raise LookupError(f"run not found: {run_id}")
        result = transition_run(
            current.status,
            command=RunCommand.FINALIZE_CANCEL,
            current_version=current.version,
            expected_version=expected_version,
        )
        if not result.applied:
            return result
        cursor = self._connection.execute(
            """
            UPDATE runs
            SET status = ?, version = ?, finished_at_ms = ?
            WHERE id = ? AND version = ?;
            """,
            (
                result.current_status.value,
                result.current_version,
                finished_at_ms,
                run_id,
                current.version,
            ),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError("run cancel finalize affected an unexpected row count")
        return result

    def set_recovery_required(self, run_id: str, *, finished_at_ms: int | None = None) -> RunRecord:
        return self._force_status(
            run_id,
            status=RunStatus.RECOVERY_REQUIRED,
            finished_at_ms=finished_at_ms,
        )

    def set_reauth_required(self, run_id: str, *, finished_at_ms: int | None = None) -> RunRecord:
        return self._force_status(
            run_id,
            status=RunStatus.REAUTH_REQUIRED,
            finished_at_ms=finished_at_ms,
        )

    def set_verifying(self, run_id: str, *, finished_at_ms: int | None = None) -> RunRecord:
        return self._force_status(
            run_id,
            status=RunStatus.VERIFYING,
            finished_at_ms=finished_at_ms,
        )

    def _force_status(
        self,
        run_id: str,
        *,
        status: RunStatus,
        finished_at_ms: int | None,
    ) -> RunRecord:
        current = self.get_by_id(run_id)
        if current is None:
            raise LookupError(f"run not found: {run_id}")
        cursor = self._connection.execute(
            """
            UPDATE runs
            SET status = ?, version = version + 1, finished_at_ms = ?
            WHERE id = ? AND version = ?;
            """,
            (status.value, finished_at_ms, run_id, current.version),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError("run force-status affected an unexpected row count")
        updated = self.get_by_id(run_id)
        if updated is None:
            raise LookupError(f"run not found after status update: {run_id}")
        return updated


class SQLiteMessageRepository:
    """SQLite message repository."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, message: MessageRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO messages (id, conversation_id, run_id, role, content, created_at_ms)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (
                message.id,
                message.conversation_id,
                message.run_id,
                message.role,
                message.content,
                message.created_at_ms,
            ),
        )

    def find_assistant_message(
        self,
        *,
        run_id: str,
        content: str,
    ) -> MessageRecord | None:
        row = self._connection.execute(
            """
            SELECT id, conversation_id, run_id, role, content, created_at_ms
            FROM messages
            WHERE run_id = ? AND role = 'ASSISTANT' AND content = ?
            ORDER BY created_at_ms DESC, id DESC
            LIMIT 1;
            """,
            (run_id, content),
        ).fetchone()
        if row is None:
            return None
        return MessageRecord(
            id=str(row["id"]),
            conversation_id=str(row["conversation_id"]),
            run_id=None if row["run_id"] is None else str(row["run_id"]),
            role=str(row["role"]),
            content=str(row["content"]),
            created_at_ms=int(row["created_at_ms"]),
        )


class SQLiteCommandReceiptRepository:
    """SQLite command receipt repository."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_by_command_id(self, command_id: str) -> CommandReceiptRecord | None:
        row = self._connection.execute(
            """
            SELECT command_id, command_type, request_hash, aggregate_type, aggregate_id,
                   status, result_code, result_version, response_json, created_at_ms,
                   completed_at_ms
            FROM command_receipts
            WHERE command_id = ?;
            """,
            (command_id,),
        ).fetchone()
        if row is None:
            return None
        response = None
        if row["response_json"] is not None and str(row["command_type"]) == "CompleteAnswerOnlyRun":
            response = _deserialize_answer_only_response(str(row["response_json"]))
        return CommandReceiptRecord(
            command_id=str(row["command_id"]),
            command_type=str(row["command_type"]),
            request_hash=str(row["request_hash"]),
            aggregate_type=str(row["aggregate_type"]),
            aggregate_id=None if row["aggregate_id"] is None else str(row["aggregate_id"]),
            status=CommandReceiptStatus(str(row["status"])),
            result_code=None if row["result_code"] is None else ResultCode(str(row["result_code"])),
            result_version=_int_or_none(row["result_version"]),
            response=response,
            response_json=None if row["response_json"] is None else str(row["response_json"]),
            created_at_ms=int(row["created_at_ms"]),
            completed_at_ms=_int_or_none(row["completed_at_ms"]),
        )

    def add_received(
        self,
        *,
        command_id: str,
        command_type: str,
        request_hash: str,
        aggregate_type: str,
        aggregate_id: str | None,
        created_at_ms: int,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO command_receipts (
                command_id, command_type, request_hash, aggregate_type, aggregate_id,
                status, created_at_ms
            )
            VALUES (?, ?, ?, ?, ?, 'RECEIVED', ?);
            """,
            (command_id, command_type, request_hash, aggregate_type, aggregate_id, created_at_ms),
        )

    def finish(
        self,
        *,
        command_id: str,
        response: AnswerOnlyResponse,
        completed_at_ms: int,
    ) -> None:
        status = CommandReceiptStatus.APPLIED if response.applied else CommandReceiptStatus.REJECTED
        cursor = self._connection.execute(
            """
            UPDATE command_receipts
            SET status = ?, result_code = ?, result_version = ?,
                response_json = ?, completed_at_ms = ?
            WHERE command_id = ?;
            """,
            (
                status.value,
                response.result_code.value,
                response.current_version,
                _serialize_answer_only_response(response),
                completed_at_ms,
                command_id,
            ),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError("receipt finalize affected an unexpected row count")

    def finish_json(
        self,
        *,
        command_id: str,
        applied: bool,
        result_code: ResultCode,
        result_version: int,
        response_json: str,
        completed_at_ms: int,
    ) -> None:
        status = CommandReceiptStatus.APPLIED if applied else CommandReceiptStatus.REJECTED
        cursor = self._connection.execute(
            """
            UPDATE command_receipts
            SET status = ?, result_code = ?, result_version = ?,
                response_json = ?, completed_at_ms = ?
            WHERE command_id = ?;
            """,
            (
                status.value,
                result_code.value,
                result_version,
                response_json,
                completed_at_ms,
                command_id,
            ),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError("receipt finalize affected an unexpected row count")


class SQLitePlanRepository:
    """SQLite plan repository."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_by_id(self, plan_id: str) -> PlanRecord | None:
        row = self._connection.execute(
            """
            SELECT id, run_id, revision_no, status, summary_text, created_at_ms
            FROM plans
            WHERE id = ?;
            """,
            (plan_id,),
        ).fetchone()
        if row is None:
            return None
        return PlanRecord(
            id=str(row["id"]),
            run_id=str(row["run_id"]),
            revision_no=int(row["revision_no"]),
            status=PlanStatus(str(row["status"])),
            summary_text=None if row["summary_text"] is None else str(row["summary_text"]),
            created_at_ms=int(row["created_at_ms"]),
        )

    def insert_draft(self, plan: PlanRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO plans (id, run_id, revision_no, status, summary_text, created_at_ms)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (
                plan.id,
                plan.run_id,
                plan.revision_no,
                plan.status.value,
                plan.summary_text,
                plan.created_at_ms,
            ),
        )

    def activate(self, plan_id: str) -> None:
        cursor = self._connection.execute(
            "UPDATE plans SET status = 'ACTIVE' WHERE id = ? AND status = 'DRAFT';",
            (plan_id,),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError("plan activation affected an unexpected row count")

    def wait_for_approval(self, plan_id: str) -> None:
        cursor = self._connection.execute(
            "UPDATE plans SET status = 'WAITING_APPROVAL' WHERE id = ? AND status = 'DRAFT';",
            (plan_id,),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError("plan wait-for-approval affected an unexpected row count")

    def activate_waiting(self, plan_id: str) -> None:
        cursor = self._connection.execute(
            """
            UPDATE plans
            SET status = 'ACTIVE'
            WHERE id = ? AND status = 'WAITING_APPROVAL';
            """,
            (plan_id,),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError(
                "waiting-approval plan activation affected an unexpected row count"
            )

    def complete(self, plan_id: str) -> None:
        cursor = self._connection.execute(
            "UPDATE plans SET status = 'COMPLETED' WHERE id = ? AND status = 'ACTIVE';",
            (plan_id,),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError("plan completion affected an unexpected row count")

    def cancel(self, plan_id: str) -> None:
        cursor = self._connection.execute(
            """
            UPDATE plans
            SET status = 'CANCELLED'
            WHERE id = ? AND status IN ('WAITING_APPROVAL', 'ACTIVE');
            """,
            (plan_id,),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError("plan cancellation affected an unexpected row count")

    def list_by_run(self, run_id: str) -> tuple[PlanRecord, ...]:
        rows = self._connection.execute(
            """
            SELECT id, run_id, revision_no, status, summary_text, created_at_ms
            FROM plans
            WHERE run_id = ?
            ORDER BY revision_no ASC;
            """,
            (run_id,),
        ).fetchall()
        return tuple(
            PlanRecord(
                id=str(row["id"]),
                run_id=str(row["run_id"]),
                revision_no=int(row["revision_no"]),
                status=PlanStatus(str(row["status"])),
                summary_text=None if row["summary_text"] is None else str(row["summary_text"]),
                created_at_ms=int(row["created_at_ms"]),
            )
            for row in rows
        )


class SQLiteActionRepository:
    """SQLite action repository with optimistic read-action transitions."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_by_id(self, action_id: str) -> ActionRecord | None:
        row = self._connection.execute(
            """
            SELECT id, plan_id, position, tool_name, effect_type, approval_requirement,
                   verification_policy, recovery_policy, target_resource_ref_id, status,
                   arguments_json, arguments_hash, expected_json, version, created_at_ms,
                   updated_at_ms
            FROM actions
            WHERE id = ?;
            """,
            (action_id,),
        ).fetchone()
        return None if row is None else _action_record_from_row(row)

    def insert_read_action(self, action: ActionRecord) -> None:
        self._insert_action(action)

    def insert_write_action(self, action: ActionRecord) -> None:
        self._insert_action(action)

    def _insert_action(self, action: ActionRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO actions (
                id, plan_id, position, tool_name, effect_type, approval_requirement,
                verification_policy, recovery_policy, target_resource_ref_id, status,
                arguments_json, arguments_hash, expected_json, version, created_at_ms, updated_at_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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
                action.version,
                action.created_at_ms,
                action.updated_at_ms,
            ),
        )

    def claim_read(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        return self._transition_read_action(
            action_id,
            command=ActionCommand.CLAIM_READ_ACTION,
            expected_version=expected_version,
            updated_at_ms=updated_at_ms,
        )

    def complete_read(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        return self._transition_read_action(
            action_id,
            command=ActionCommand.COMPLETE_READ_ACTION,
            expected_version=expected_version,
            updated_at_ms=updated_at_ms,
        )

    def finalize_read(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        return self._transition_read_action(
            action_id,
            command=ActionCommand.FINALIZE_READ_ACTION,
            expected_version=expected_version,
            updated_at_ms=updated_at_ms,
        )

    def fail_read(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        return self._transition_read_action(
            action_id,
            command=ActionCommand.FAIL_READ_ACTION,
            expected_version=expected_version,
            updated_at_ms=updated_at_ms,
        )

    def approve_write(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        return self._transition_write_action(
            action_id,
            command=ActionCommand.APPROVE_ACTION,
            expected_version=expected_version,
            updated_at_ms=updated_at_ms,
        )

    def reject_write(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        return self._transition_write_action(
            action_id,
            command=ActionCommand.REJECT_ACTION,
            expected_version=expected_version,
            updated_at_ms=updated_at_ms,
        )

    def claim_execution(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        return self._transition_write_action(
            action_id,
            command=ActionCommand.CLAIM_EXECUTION,
            expected_version=expected_version,
            updated_at_ms=updated_at_ms,
        )

    def store_success(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        return self._transition_write_action(
            action_id,
            command=ActionCommand.STORE_SUCCESS,
            expected_version=expected_version,
            updated_at_ms=updated_at_ms,
        )

    def mark_failed(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        return self._transition_write_action(
            action_id,
            command=ActionCommand.MARK_FAILED,
            expected_version=expected_version,
            updated_at_ms=updated_at_ms,
        )

    def mark_unknown_result(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        return self._transition_write_action(
            action_id,
            command=ActionCommand.MARK_UNKNOWN_RESULT,
            expected_version=expected_version,
            updated_at_ms=updated_at_ms,
        )

    def recover_existing_result(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        return self._transition_write_action(
            action_id,
            command=ActionCommand.RECOVER_EXISTING_RESULT,
            expected_version=expected_version,
            updated_at_ms=updated_at_ms,
        )

    def resolve_unknown_as_failed(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        current = self.get_by_id(action_id)
        if current is None:
            raise LookupError(f"action not found: {action_id}")
        result = transition_action(
            ActionStatus(current.status),
            command=ActionCommand.RESOLVE_AS_FAILED,
            current_version=current.version,
            expected_version=expected_version,
            effect_type=EffectType(current.effect_type),
            result_not_executed_confirmed=True,
        )
        if not result.applied:
            return result
        cursor = self._connection.execute(
            """
            UPDATE actions
            SET status = ?, version = ?, updated_at_ms = ?
            WHERE id = ? AND version = ?;
            """,
            (
                result.current_status.value,
                result.current_version,
                updated_at_ms,
                action_id,
                current.version,
            ),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError(
                "write action resolve-as-failed affected an unexpected row count"
            )
        return result

    def prepare_write_retry(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        return self._transition_write_action(
            action_id,
            command=ActionCommand.PREPARE_WRITE_RETRY,
            expected_version=expected_version,
            updated_at_ms=updated_at_ms,
        )

    def store_verification(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
        verification_status: str,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        current = self.get_by_id(action_id)
        if current is None:
            raise LookupError(f"action not found: {action_id}")
        result = transition_action(
            ActionStatus(current.status),
            command=ActionCommand.STORE_VERIFICATION,
            current_version=current.version,
            expected_version=expected_version,
            effect_type=EffectType(current.effect_type),
            verification_status=VerificationStatus(verification_status),
        )
        if not result.applied:
            return result
        cursor = self._connection.execute(
            """
            UPDATE actions
            SET status = ?, version = ?, updated_at_ms = ?
            WHERE id = ? AND version = ?;
            """,
            (
                result.current_status.value,
                result.current_version,
                updated_at_ms,
                action_id,
                current.version,
            ),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError("write verification affected an unexpected row count")
        return result

    def mark_dependency_blocked(self, action_id: str, *, updated_at_ms: int) -> bool:
        cursor = self._connection.execute(
            """
            UPDATE actions
            SET status = 'DEPENDENCY_BLOCKED', version = version + 1, updated_at_ms = ?
            WHERE id = ? AND status = 'PROPOSED';
            """,
            (updated_at_ms, action_id),
        )
        if cursor.rowcount > 1:
            raise sqlite3.IntegrityError(
                "dependency blocked update affected an unexpected row count"
            )
        return cursor.rowcount == 1

    def list_by_plan(self, plan_id: str) -> tuple[ActionRecord, ...]:
        rows = self._connection.execute(
            """
            SELECT id, plan_id, position, tool_name, effect_type, approval_requirement,
                   verification_policy, recovery_policy, target_resource_ref_id, status,
                   arguments_json, arguments_hash, expected_json, version, created_at_ms,
                   updated_at_ms
            FROM actions
            WHERE plan_id = ?
            ORDER BY position ASC;
            """,
            (plan_id,),
        ).fetchall()
        return tuple(_action_record_from_row(row) for row in rows)

    def list_ready_actions(self, plan_id: str) -> tuple[ActionRecord, ...]:
        rows = self._connection.execute(
            """
            SELECT a.id, a.plan_id, a.position, a.tool_name, a.effect_type,
                   a.approval_requirement, a.verification_policy, a.recovery_policy,
                   a.target_resource_ref_id, a.status, a.arguments_json, a.arguments_hash,
                   a.expected_json, a.version, a.created_at_ms, a.updated_at_ms
            FROM actions AS a
            WHERE a.plan_id = ?
              AND a.status = 'PROPOSED'
              AND NOT EXISTS (
                    SELECT 1
                    FROM action_dependencies AS d
                    JOIN actions AS dep ON dep.id = d.depends_on_action_id
                    WHERE d.action_id = a.id
                      AND dep.status <> 'VERIFIED'
              )
            ORDER BY a.position ASC;
            """,
            (plan_id,),
        ).fetchall()
        return tuple(_action_record_from_row(row) for row in rows)

    def _transition_read_action(
        self,
        action_id: str,
        *,
        command: ActionCommand,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        current = self.get_by_id(action_id)
        if current is None:
            raise LookupError(f"action not found: {action_id}")
        result = transition_action(
            ActionStatus(current.status),
            command=command,
            current_version=current.version,
            expected_version=expected_version,
            effect_type=EffectType.READ,
        )
        if not result.applied:
            return result
        cursor = self._connection.execute(
            """
            UPDATE actions
            SET status = ?, version = ?, updated_at_ms = ?
            WHERE id = ? AND version = ?;
            """,
            (
                result.current_status.value,
                result.current_version,
                updated_at_ms,
                action_id,
                current.version,
            ),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError("read action transition affected an unexpected row count")
        return result

    def _transition_write_action(
        self,
        action_id: str,
        *,
        command: ActionCommand,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        current = self.get_by_id(action_id)
        if current is None:
            raise LookupError(f"action not found: {action_id}")
        result = transition_action(
            ActionStatus(current.status),
            command=command,
            current_version=current.version,
            expected_version=expected_version,
            effect_type=EffectType(current.effect_type),
        )
        if not result.applied:
            return result
        cursor = self._connection.execute(
            """
            UPDATE actions
            SET status = ?, version = ?, updated_at_ms = ?
            WHERE id = ? AND version = ?;
            """,
            (
                result.current_status.value,
                result.current_version,
                updated_at_ms,
                action_id,
                current.version,
            ),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError("write action transition affected an unexpected row count")
        return result


class SQLiteResourceRefRepository:
    """SQLite resource reference repository."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_by_id(self, resource_ref_id: str) -> ResourceRefRecord | None:
        row = self._connection.execute(
            """
            SELECT id, run_id, source, resource_type, resource_id, parent_resource_id,
                   canonical_url, title, event_time_ms, version_token, metadata_json, captured_at_ms
            FROM resource_refs
            WHERE id = ?;
            """,
            (resource_ref_id,),
        ).fetchone()
        return None if row is None else _resource_ref_record_from_row(row)

    def get_by_unique_key(
        self,
        *,
        run_id: str,
        source: str,
        resource_type: str,
        resource_id: str,
    ) -> ResourceRefRecord | None:
        row = self._connection.execute(
            """
            SELECT id, run_id, source, resource_type, resource_id, parent_resource_id,
                   canonical_url, title, event_time_ms, version_token, metadata_json, captured_at_ms
            FROM resource_refs
            WHERE run_id = ? AND source = ? AND resource_type = ? AND resource_id = ?;
            """,
            (run_id, source, resource_type, resource_id),
        ).fetchone()
        return None if row is None else _resource_ref_record_from_row(row)

    def upsert(self, record: ResourceRefRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO resource_refs (
                id, run_id, source, resource_type, resource_id, parent_resource_id,
                canonical_url, title, event_time_ms, version_token, metadata_json, captured_at_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, source, resource_type, resource_id)
            DO UPDATE SET
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
            """
            SELECT id, run_id, source, resource_type, resource_id, parent_resource_id,
                   canonical_url, title, event_time_ms, version_token, metadata_json, captured_at_ms
            FROM resource_refs
            WHERE run_id = ?
            ORDER BY source, resource_type, resource_id;
            """,
            (run_id,),
        ).fetchall()
        return tuple(_resource_ref_record_from_row(row) for row in rows)


class SQLiteEvidenceRepository:
    """SQLite evidence repository."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def insert(self, record: EvidenceRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO evidence (
                id, run_id, origin_type, resource_ref_id, message_id, kind,
                excerpt, locator_json, created_at_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                record.id,
                record.run_id,
                record.origin_type.value,
                record.resource_ref_id,
                record.message_id,
                record.kind,
                record.excerpt,
                record.locator_json,
                record.created_at_ms,
            ),
        )

    def link_to_action(self, *, action_id: str, evidence_id: str) -> None:
        self._connection.execute(
            """
            INSERT OR IGNORE INTO action_evidence (action_id, evidence_id)
            VALUES (?, ?);
            """,
            (action_id, evidence_id),
        )

    def list_by_action(self, action_id: str) -> tuple[EvidenceRecord, ...]:
        rows = self._connection.execute(
            """
            SELECT e.id, e.run_id, e.origin_type, e.resource_ref_id, e.message_id, e.kind,
                   e.excerpt, e.locator_json, e.created_at_ms
            FROM evidence AS e
            JOIN action_evidence AS ae ON ae.evidence_id = e.id
            WHERE ae.action_id = ?
            ORDER BY e.created_at_ms ASC, e.id ASC;
            """,
            (action_id,),
        ).fetchall()
        return tuple(_evidence_record_from_row(row) for row in rows)


class SQLiteActionDependencyRepository:
    """SQLite action dependency repository."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, *, action_id: str, depends_on_action_id: str) -> None:
        self._connection.execute(
            """
            INSERT INTO action_dependencies (action_id, depends_on_action_id)
            VALUES (?, ?);
            """,
            (action_id, depends_on_action_id),
        )

    def list_dependencies(self, action_id: str) -> tuple[str, ...]:
        rows = self._connection.execute(
            """
            SELECT depends_on_action_id
            FROM action_dependencies
            WHERE action_id = ?
            ORDER BY depends_on_action_id ASC;
            """,
            (action_id,),
        ).fetchall()
        return tuple(str(row["depends_on_action_id"]) for row in rows)

    def list_dependents(self, action_id: str) -> tuple[str, ...]:
        rows = self._connection.execute(
            """
            SELECT action_id
            FROM action_dependencies
            WHERE depends_on_action_id = ?
            ORDER BY action_id ASC;
            """,
            (action_id,),
        ).fetchall()
        return tuple(str(row["action_id"]) for row in rows)


class SQLiteApprovalRepository:
    """SQLite approval repository."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_by_id(self, approval_id: str) -> ApprovalRecord | None:
        row = self._connection.execute(
            """
            SELECT id, action_id, approval_no, action_version, status, approved_by_account_id,
                   approved_by_display, arguments_snapshot_json, canonical_arguments_hash,
                   source_snapshot_json, source_snapshot_hash, policy_version,
                   tool_schema_version, idempotency_key, recovery_fingerprint,
                   approved_at_ms, expires_at_ms, consumed_at_ms
            FROM approvals
            WHERE id = ?;
            """,
            (approval_id,),
        ).fetchone()
        return None if row is None else _approval_record_from_row(row)

    def get_active_by_action(self, action_id: str) -> ApprovalRecord | None:
        row = self._connection.execute(
            """
            SELECT id, action_id, approval_no, action_version, status, approved_by_account_id,
                   approved_by_display, arguments_snapshot_json, canonical_arguments_hash,
                   source_snapshot_json, source_snapshot_hash, policy_version,
                   tool_schema_version, idempotency_key, recovery_fingerprint,
                   approved_at_ms, expires_at_ms, consumed_at_ms
            FROM approvals
            WHERE action_id = ? AND status = 'ACTIVE'
            ORDER BY approval_no DESC
            LIMIT 1;
            """,
            (action_id,),
        ).fetchone()
        return None if row is None else _approval_record_from_row(row)

    def insert(self, record: ApprovalRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO approvals (
                id, action_id, approval_no, action_version, status, approved_by_account_id,
                approved_by_display, arguments_snapshot_json, canonical_arguments_hash,
                source_snapshot_json, source_snapshot_hash, policy_version, tool_schema_version,
                idempotency_key, recovery_fingerprint, approved_at_ms, expires_at_ms, consumed_at_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                record.id,
                record.action_id,
                record.approval_no,
                record.action_version,
                record.status.value,
                record.approved_by_account_id,
                record.approved_by_display,
                record.arguments_snapshot_json,
                record.canonical_arguments_hash,
                record.source_snapshot_json,
                record.source_snapshot_hash,
                record.policy_version,
                record.tool_schema_version,
                record.idempotency_key,
                record.recovery_fingerprint,
                record.approved_at_ms,
                record.expires_at_ms,
                record.consumed_at_ms,
            ),
        )

    def mark_consumed(self, approval_id: str, *, consumed_at_ms: int) -> None:
        cursor = self._connection.execute(
            """
            UPDATE approvals
            SET status = 'CONSUMED', consumed_at_ms = ?
            WHERE id = ? AND status = 'ACTIVE';
            """,
            (consumed_at_ms, approval_id),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError("approval consume affected an unexpected row count")

    def revoke_active_by_action(self, action_id: str) -> tuple[str, ...]:
        rows = self._connection.execute(
            """
            SELECT id
            FROM approvals
            WHERE action_id = ? AND status = 'ACTIVE'
            ORDER BY approval_no ASC;
            """,
            (action_id,),
        ).fetchall()
        approval_ids = tuple(str(row["id"]) for row in rows)
        if not approval_ids:
            return ()
        cursor = self._connection.execute(
            """
            UPDATE approvals
            SET status = 'REVOKED'
            WHERE action_id = ? AND status = 'ACTIVE';
            """,
            (action_id,),
        )
        if cursor.rowcount != len(approval_ids):
            raise sqlite3.IntegrityError("approval revoke affected an unexpected row count")
        return approval_ids

    def list_by_action(self, action_id: str) -> tuple[ApprovalRecord, ...]:
        rows = self._connection.execute(
            """
            SELECT id, action_id, approval_no, action_version, status, approved_by_account_id,
                   approved_by_display, arguments_snapshot_json, canonical_arguments_hash,
                   source_snapshot_json, source_snapshot_hash, policy_version,
                   tool_schema_version, idempotency_key, recovery_fingerprint,
                   approved_at_ms, expires_at_ms, consumed_at_ms
            FROM approvals
            WHERE action_id = ?
            ORDER BY approval_no ASC;
            """,
            (action_id,),
        ).fetchall()
        return tuple(_approval_record_from_row(row) for row in rows)


class SQLiteExecutionAttemptRepository:
    """SQLite execution attempt repository."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_by_id(self, attempt_id: str) -> ExecutionAttemptRecord | None:
        row = self._connection.execute(
            """
            SELECT id, approval_id, attempt_no, status, version, result_resource_ref_id,
                   response_metadata_json, error_code, error_detail_json,
                   started_at_ms, finished_at_ms
            FROM execution_attempts
            WHERE id = ?;
            """,
            (attempt_id,),
        ).fetchone()
        return None if row is None else _execution_attempt_record_from_row(row)

    def get_active_by_approval(self, approval_id: str) -> ExecutionAttemptRecord | None:
        row = self._connection.execute(
            """
            SELECT id, approval_id, attempt_no, status, version, result_resource_ref_id,
                   response_metadata_json, error_code, error_detail_json,
                   started_at_ms, finished_at_ms
            FROM execution_attempts
            WHERE approval_id = ?
              AND status IN ('CLAIMED', 'EXECUTING', 'UNKNOWN_RESULT')
            ORDER BY attempt_no DESC
            LIMIT 1;
            """,
            (approval_id,),
        ).fetchone()
        return None if row is None else _execution_attempt_record_from_row(row)

    def insert_claimed(self, record: ExecutionAttemptRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO execution_attempts (
                id, approval_id, attempt_no, status, version, result_resource_ref_id,
                response_metadata_json, error_code, error_detail_json, started_at_ms, finished_at_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                record.id,
                record.approval_id,
                record.attempt_no,
                record.status.value,
                record.version,
                record.result_resource_ref_id,
                record.response_metadata_json,
                record.error_code,
                record.error_detail_json,
                record.started_at_ms,
                record.finished_at_ms,
            ),
        )

    def mark_succeeded(
        self,
        attempt_id: str,
        *,
        expected_version: int,
        result_resource_ref_id: str | None,
        response_metadata_json: str | None,
        finished_at_ms: int,
    ) -> ExecutionAttemptRecord:
        current = self.get_by_id(attempt_id)
        if current is None:
            raise LookupError(f"execution attempt not found: {attempt_id}")
        if current.version != expected_version:
            raise sqlite3.IntegrityError("execution attempt version conflict")
        cursor = self._connection.execute(
            """
            UPDATE execution_attempts
            SET status = 'SUCCEEDED',
                version = version + 1,
                result_resource_ref_id = ?,
                response_metadata_json = ?,
                finished_at_ms = ?
            WHERE id = ? AND version = ?;
            """,
            (
                result_resource_ref_id,
                response_metadata_json,
                finished_at_ms,
                attempt_id,
                expected_version,
            ),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError(
                "execution attempt success affected an unexpected row count"
            )
        updated = self.get_by_id(attempt_id)
        if updated is None:
            raise LookupError(f"execution attempt not found after success: {attempt_id}")
        return updated

    def mark_failed(
        self,
        attempt_id: str,
        *,
        expected_version: int,
        error_code: str,
        error_detail_json: str,
        finished_at_ms: int,
    ) -> ExecutionAttemptRecord:
        current = self.get_by_id(attempt_id)
        if current is None:
            raise LookupError(f"execution attempt not found: {attempt_id}")
        if current.version != expected_version:
            raise sqlite3.IntegrityError("execution attempt version conflict")
        cursor = self._connection.execute(
            """
            UPDATE execution_attempts
            SET status = 'FAILED',
                version = version + 1,
                error_code = ?,
                error_detail_json = ?,
                finished_at_ms = ?
            WHERE id = ? AND version = ?;
            """,
            (
                error_code,
                error_detail_json,
                finished_at_ms,
                attempt_id,
                expected_version,
            ),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError(
                "execution attempt failure affected an unexpected row count"
            )
        updated = self.get_by_id(attempt_id)
        if updated is None:
            raise LookupError(f"execution attempt not found after failure: {attempt_id}")
        return updated

    def mark_unknown_result(
        self,
        attempt_id: str,
        *,
        expected_version: int,
        error_code: str,
        error_detail_json: str,
        finished_at_ms: int,
    ) -> ExecutionAttemptRecord:
        return self.update_status(
            attempt_id,
            expected_version=expected_version,
            status=ExecutionAttemptStatus.UNKNOWN_RESULT,
            error_code=error_code,
            error_detail_json=error_detail_json,
            result_resource_ref_id=None,
            response_metadata_json=None,
            finished_at_ms=finished_at_ms,
        )

    def update_status(
        self,
        attempt_id: str,
        *,
        expected_version: int,
        status: ExecutionAttemptStatus,
        error_code: str | None,
        error_detail_json: str | None,
        result_resource_ref_id: str | None,
        response_metadata_json: str | None,
        finished_at_ms: int | None,
    ) -> ExecutionAttemptRecord:
        current = self.get_by_id(attempt_id)
        if current is None:
            raise LookupError(f"execution attempt not found: {attempt_id}")
        if current.version != expected_version:
            raise sqlite3.IntegrityError("execution attempt version conflict")
        cursor = self._connection.execute(
            """
            UPDATE execution_attempts
            SET status = ?,
                version = version + 1,
                result_resource_ref_id = ?,
                response_metadata_json = ?,
                error_code = ?,
                error_detail_json = ?,
                finished_at_ms = ?
            WHERE id = ? AND version = ?;
            """,
            (
                status.value,
                result_resource_ref_id,
                response_metadata_json,
                error_code,
                error_detail_json,
                finished_at_ms,
                attempt_id,
                expected_version,
            ),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError(
                "execution attempt update affected an unexpected row count"
            )
        updated = self.get_by_id(attempt_id)
        if updated is None:
            raise LookupError(f"execution attempt not found after update: {attempt_id}")
        return updated

    def list_by_approval(self, approval_id: str) -> tuple[ExecutionAttemptRecord, ...]:
        rows = self._connection.execute(
            """
            SELECT id, approval_id, attempt_no, status, version, result_resource_ref_id,
                   response_metadata_json, error_code, error_detail_json,
                   started_at_ms, finished_at_ms
            FROM execution_attempts
            WHERE approval_id = ?
            ORDER BY attempt_no ASC;
            """,
            (approval_id,),
        ).fetchall()
        return tuple(_execution_attempt_record_from_row(row) for row in rows)


class SQLiteVerificationRepository:
    """SQLite verification repository."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def insert(self, record: VerificationRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO verifications (
                id, execution_attempt_id, verification_no, status, normalizer_version,
                expected_json, actual_json, diff_json, verified_at_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                record.id,
                record.execution_attempt_id,
                record.verification_no,
                record.status.value,
                record.normalizer_version,
                record.expected_json,
                record.actual_json,
                record.diff_json,
                record.verified_at_ms,
            ),
        )

    def list_by_attempt(self, execution_attempt_id: str) -> tuple[VerificationRecord, ...]:
        rows = self._connection.execute(
            """
            SELECT id, execution_attempt_id, verification_no, status, normalizer_version,
                   expected_json, actual_json, diff_json, verified_at_ms
            FROM verifications
            WHERE execution_attempt_id = ?
            ORDER BY verification_no ASC;
            """,
            (execution_attempt_id,),
        ).fetchall()
        return tuple(_verification_record_from_row(row) for row in rows)


class SQLiteAuditRepository:
    """Append-only SQLite audit repository."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, event: AuditEventRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO audit_events (
                account_id, run_id, action_id, actor_type, actor_id, actor_display,
                event_type, outcome, metadata_json, created_at_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                event.account_id,
                event.run_id,
                event.action_id,
                event.actor_type,
                event.actor_id,
                event.actor_display,
                event.event_type,
                event.outcome,
                event.metadata_json,
                event.created_at_ms,
            ),
        )


class SQLiteTraceRepository:
    """Append-only SQLite trace repository."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, event: TraceEventRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO trace_events (
                run_id, action_id, event_type, status, duration_ms, payload_json, created_at_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                event.run_id,
                event.action_id,
                event.event_type,
                event.status,
                event.duration_ms,
                event.payload_json,
                event.created_at_ms,
            ),
        )


def _serialize_answer_only_response(response: AnswerOnlyResponse) -> str:
    return dumps(
        {
            "applied": response.applied,
            "result_code": response.result_code.value,
            "current_status": response.current_status.value,
            "current_version": response.current_version,
            "next_allowed_commands": [command.value for command in response.next_allowed_commands],
            "conflict_detail": response.conflict_detail,
            "assistant_message_id": response.assistant_message_id,
        },
        sort_keys=True,
    )


def _deserialize_answer_only_response(raw: str) -> AnswerOnlyResponse:
    payload = loads(raw)
    return AnswerOnlyResponse(
        applied=bool(payload["applied"]),
        result_code=ResultCode(str(payload["result_code"])),
        current_status=RunStatus(str(payload["current_status"])),
        current_version=int(payload["current_version"]),
        next_allowed_commands=tuple(
            RunCommand(str(command_value)) for command_value in payload["next_allowed_commands"]
        ),
        conflict_detail=payload["conflict_detail"],
        assistant_message_id=payload["assistant_message_id"],
    )


def _action_record_from_row(row: sqlite3.Row) -> ActionRecord:
    return ActionRecord(
        id=str(row["id"]),
        plan_id=str(row["plan_id"]),
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
        version=int(row["version"]),
        created_at_ms=int(row["created_at_ms"]),
        updated_at_ms=int(row["updated_at_ms"]),
    )


def _resource_ref_record_from_row(row: sqlite3.Row) -> ResourceRefRecord:
    return ResourceRefRecord(
        id=str(row["id"]),
        run_id=str(row["run_id"]),
        source=ResourceSource(str(row["source"])),
        resource_type=StoredResourceType(str(row["resource_type"])),
        resource_id=str(row["resource_id"]),
        parent_resource_id=(
            None if row["parent_resource_id"] is None else str(row["parent_resource_id"])
        ),
        canonical_url=None if row["canonical_url"] is None else str(row["canonical_url"]),
        title=None if row["title"] is None else str(row["title"]),
        event_time_ms=_int_or_none(row["event_time_ms"]),
        version_token=None if row["version_token"] is None else str(row["version_token"]),
        metadata_json=str(row["metadata_json"]),
        captured_at_ms=int(row["captured_at_ms"]),
    )


def _evidence_record_from_row(row: sqlite3.Row) -> EvidenceRecord:
    return EvidenceRecord(
        id=str(row["id"]),
        run_id=str(row["run_id"]),
        origin_type=EvidenceOriginType(str(row["origin_type"])),
        resource_ref_id=None if row["resource_ref_id"] is None else str(row["resource_ref_id"]),
        message_id=None if row["message_id"] is None else str(row["message_id"]),
        kind=str(row["kind"]),
        excerpt=str(row["excerpt"]),
        locator_json=None if row["locator_json"] is None else str(row["locator_json"]),
        created_at_ms=int(row["created_at_ms"]),
    )


def _approval_record_from_row(row: sqlite3.Row) -> ApprovalRecord:
    return ApprovalRecord(
        id=str(row["id"]),
        action_id=str(row["action_id"]),
        approval_no=int(row["approval_no"]),
        action_version=int(row["action_version"]),
        status=ApprovalStatus(str(row["status"])),
        approved_by_account_id=str(row["approved_by_account_id"]),
        approved_by_display=(
            None if row["approved_by_display"] is None else str(row["approved_by_display"])
        ),
        arguments_snapshot_json=str(row["arguments_snapshot_json"]),
        canonical_arguments_hash=str(row["canonical_arguments_hash"]),
        source_snapshot_json=str(row["source_snapshot_json"]),
        source_snapshot_hash=str(row["source_snapshot_hash"]),
        policy_version=str(row["policy_version"]),
        tool_schema_version=str(row["tool_schema_version"]),
        idempotency_key=str(row["idempotency_key"]),
        recovery_fingerprint=str(row["recovery_fingerprint"]),
        approved_at_ms=int(row["approved_at_ms"]),
        expires_at_ms=int(row["expires_at_ms"]),
        consumed_at_ms=_int_or_none(row["consumed_at_ms"]),
    )


def _execution_attempt_record_from_row(row: sqlite3.Row) -> ExecutionAttemptRecord:
    return ExecutionAttemptRecord(
        id=str(row["id"]),
        approval_id=str(row["approval_id"]),
        attempt_no=int(row["attempt_no"]),
        status=ExecutionAttemptStatus(str(row["status"])),
        version=int(row["version"]),
        result_resource_ref_id=(
            None if row["result_resource_ref_id"] is None else str(row["result_resource_ref_id"])
        ),
        response_metadata_json=(
            None if row["response_metadata_json"] is None else str(row["response_metadata_json"])
        ),
        error_code=None if row["error_code"] is None else str(row["error_code"]),
        error_detail_json=(
            None if row["error_detail_json"] is None else str(row["error_detail_json"])
        ),
        started_at_ms=int(row["started_at_ms"]),
        finished_at_ms=_int_or_none(row["finished_at_ms"]),
    )


def _verification_record_from_row(row: sqlite3.Row) -> VerificationRecord:
    return VerificationRecord(
        id=str(row["id"]),
        execution_attempt_id=str(row["execution_attempt_id"]),
        verification_no=int(row["verification_no"]),
        status=VerificationStatus(str(row["status"])),
        normalizer_version=str(row["normalizer_version"]),
        expected_json=str(row["expected_json"]),
        actual_json=None if row["actual_json"] is None else str(row["actual_json"]),
        diff_json=str(row["diff_json"]),
        verified_at_ms=int(row["verified_at_ms"]),
    )


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise TypeError(f"expected int-compatible value, got {type(value)!r}")
