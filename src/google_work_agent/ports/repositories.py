"""Repository and transaction port definitions."""

from contextlib import AbstractContextManager
from typing import Protocol

from google_work_agent.domain import (
    ActionCommand,
    ActionStatus,
    CommandResult,
    ExecutionAttemptStatus,
    ResultCode,
    RunCommand,
    RunStatus,
)
from google_work_agent.ports.models import (
    ActionRecord,
    AnswerOnlyResponse,
    ApprovalRecord,
    AuditEventRecord,
    CommandReceiptRecord,
    ConversationRecord,
    EvidenceRecord,
    ExecutionAttemptRecord,
    MessageRecord,
    PersistedAuditEventRecord,
    PersistedTraceEventRecord,
    PlanRecord,
    ResourceRefRecord,
    RunCreateRecord,
    RunRecord,
    TraceEventRecord,
    VerificationRecord,
)


class ConversationRepository(Protocol):
    """Conversation access required by product-core application services."""

    def get_by_id(self, conversation_id: str) -> ConversationRecord | None:
        """Return a conversation by identifier."""

    def add(self, conversation: ConversationRecord) -> None:
        """Persist a new conversation row."""

    def touch(self, conversation_id: str, *, updated_at_ms: int) -> None:
        """Advance the conversation's last-activity timestamp, never backward."""


class RunRepository(Protocol):
    """Run access and state transition persistence."""

    def get_by_id(self, run_id: str) -> RunRecord | None:
        """Return a run by identifier."""

    def add(self, run: RunCreateRecord) -> None:
        """Persist a new run row."""

    def start_analysis(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int | None = None,
    ) -> CommandResult[RunStatus, RunCommand]:
        """Transition one run from CREATED into ANALYZING."""

    def begin_retrieval(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int | None = None,
    ) -> CommandResult[RunStatus, RunCommand]:
        """Transition one run into RETRIEVING."""

    def begin_planning(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int | None = None,
    ) -> CommandResult[RunStatus, RunCommand]:
        """Transition one run into PLANNING."""

    def replan(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int | None = None,
    ) -> CommandResult[RunStatus, RunCommand]:
        """Move a waiting-approval run back to PLANNING for a new revision."""

    def request_confirmation(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int | None = None,
    ) -> CommandResult[RunStatus, RunCommand]:
        """Transition one run into WAITING_CONFIRMATION."""

    def complete_answer_only_run(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int,
    ) -> CommandResult[RunStatus, RunCommand]:
        """Complete a run through the answer-only transition path."""

    def complete_write_run(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int,
    ) -> CommandResult[RunStatus, RunCommand]:
        """Complete a verified write run once all actions are terminal."""

    def finalize_action_outcomes(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int,
    ) -> CommandResult[RunStatus, RunCommand]:
        """Complete a run after all action outcomes are terminal."""

    def block_run(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int,
    ) -> CommandResult[RunStatus, RunCommand]:
        """Transition one semantic/product blocked run into BLOCKED."""

    def fail_run(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int,
    ) -> CommandResult[RunStatus, RunCommand]:
        """Transition one unrecoverable pre-effect run into FAILED."""

    def publish_read_only_plan(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int | None = None,
    ) -> CommandResult[RunStatus, RunCommand]:
        """Publish a read-only plan by moving the run into EXECUTING."""

    def complete_read_only_run(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int,
    ) -> CommandResult[RunStatus, RunCommand]:
        """Complete a read-only run once all actions are terminal."""

    def publish_write_plan(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int | None = None,
    ) -> CommandResult[RunStatus, RunCommand]:
        """Publish a write plan by moving the run into WAITING_APPROVAL."""

    def request_cancel(
        self,
        run_id: str,
        *,
        expected_version: int,
    ) -> CommandResult[RunStatus, RunCommand]:
        """Transition a run into CANCEL_REQUESTED."""

    def finalize_cancel(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int,
    ) -> CommandResult[RunStatus, RunCommand]:
        """Transition a run into CANCELLED."""

    def require_reauth(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int | None = None,
    ) -> CommandResult[RunStatus, RunCommand]:
        """Transition one run into REAUTH_REQUIRED."""

    def require_recovery(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int | None = None,
    ) -> CommandResult[RunStatus, RunCommand]:
        """Transition one non-terminal run into RECOVERY_REQUIRED."""

    def resolve_recovery(
        self,
        run_id: str,
        *,
        expected_version: int,
        recovery_next_status: RunStatus,
        finished_at_ms: int | None = None,
    ) -> CommandResult[RunStatus, RunCommand]:
        """Transition one RECOVERY_REQUIRED run into the resolved recovery status."""

    def set_recovery_required(self, run_id: str, *, finished_at_ms: int | None = None) -> RunRecord:
        """Move one run into RECOVERY_REQUIRED and bump its version."""

    def set_reauth_required(self, run_id: str, *, finished_at_ms: int | None = None) -> RunRecord:
        """Move one run into REAUTH_REQUIRED via the guarded REQUIRE_REAUTH transition."""

    def set_verifying(self, run_id: str, *, finished_at_ms: int | None = None) -> RunRecord:
        """Move one run into VERIFYING via the guarded BEGIN_VERIFICATION/recovery transition."""


class MessageRepository(Protocol):
    """Message persistence required by the answer-only flow."""

    def add(self, message: MessageRecord) -> None:
        """Persist a new message row."""

    def find_assistant_message(
        self,
        *,
        run_id: str,
        content: str,
    ) -> MessageRecord | None:
        """Return a matching assistant message if one already exists."""


class CommandReceiptRepository(Protocol):
    """Command receipt persistence for durable idempotency."""

    def get_by_command_id(self, command_id: str) -> CommandReceiptRecord | None:
        """Return an existing command receipt."""

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
        """Insert a new RECEIVED receipt inside the active transaction."""

    def finish(
        self,
        *,
        command_id: str,
        response: AnswerOnlyResponse,
        completed_at_ms: int,
    ) -> None:
        """Finalize a receipt as APPLIED or REJECTED with a stored response."""

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
        """Finalize a receipt with an arbitrary JSON response payload."""


class PlanRepository(Protocol):
    """Read-only plan persistence."""

    def get_by_id(self, plan_id: str) -> PlanRecord | None:
        """Return a plan by identifier."""

    def insert_draft(self, plan: PlanRecord) -> None:
        """Persist a new draft plan."""

    def require_review(self, plan_id: str) -> int:
        """Invalidate the prior review and return the new review generation."""

    def store_review_result(
        self,
        plan_id: str,
        *,
        expected_review_version: int,
        review_status: str,
    ) -> bool:
        """Store a review result only for the generation that was reviewed."""

    def activate(self, plan_id: str) -> None:
        """Promote a draft plan to ACTIVE."""

    def wait_for_approval(self, plan_id: str) -> None:
        """Promote a draft plan to WAITING_APPROVAL."""

    def activate_waiting(self, plan_id: str) -> None:
        """Promote a WAITING_APPROVAL plan to ACTIVE."""

    def complete(self, plan_id: str) -> None:
        """Mark a plan as COMPLETED."""

    def cancel(self, plan_id: str) -> None:
        """Mark a waiting or active plan as CANCELLED."""

    def supersede(self, plan_id: str) -> None:
        """Mark the prior recovery plan as SUPERSEDED."""

    def list_by_run(self, run_id: str) -> tuple[PlanRecord, ...]:
        """Return plans for one run."""


class ActionRepository(Protocol):
    """Read-only action persistence."""

    def get_by_id(self, action_id: str) -> ActionRecord | None:
        """Return an action by identifier."""

    def insert_read_action(self, action: ActionRecord) -> None:
        """Persist a new read action."""

    def insert_write_action(self, action: ActionRecord) -> None:
        """Persist a new write action."""

    def claim_read(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        """Transition a read action into EXECUTING."""

    def complete_read(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        """Transition a read action into EXECUTED."""

    def finalize_read(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        """Transition a read action into VERIFIED."""

    def fail_read(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        """Transition a read action into FAILED."""

    def approve_write(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        """Transition a write action into APPROVED."""

    def reject_write(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        """Transition a write action into REJECTED."""

    def modify_write(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
        arguments_json: str,
        arguments_hash: str,
        risk: dict[str, object],
    ) -> CommandResult[ActionStatus, ActionCommand]:
        """Transition to MODIFIED and atomically replace arguments and risk."""

    def update_risk_snapshot(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
        risk: dict[str, object],
    ) -> None:
        """Replace server-owned risk without changing lifecycle status/version."""

    def claim_execution(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        """Transition a write action into EXECUTING."""

    def store_success(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        """Transition a write action into EXECUTED."""

    def mark_failed(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        """Transition a write action into FAILED."""

    def mark_unknown_result(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        """Transition a write action into UNKNOWN_RESULT."""

    def recover_existing_result(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        """Transition a write action from UNKNOWN_RESULT into EXECUTED."""

    def resolve_unknown_as_failed(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        """Transition a write action from UNKNOWN_RESULT into FAILED."""

    def prepare_write_retry(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        """Transition a failed write action back into MODIFIED."""

    def cancel_pending(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        """Cancel a pending action without creating an attempt or verification."""

    def store_verification(
        self,
        action_id: str,
        *,
        expected_version: int,
        updated_at_ms: int,
        verification_status: str,
    ) -> CommandResult[ActionStatus, ActionCommand]:
        """Transition a write action into VERIFIED or MISMATCH."""

    def mark_dependency_blocked(self, action_id: str, *, updated_at_ms: int) -> bool:
        """Block one unexecuted pending action after an upstream terminal failure."""

    def list_by_plan(self, plan_id: str) -> tuple[ActionRecord, ...]:
        """Return actions for one plan."""

    def list_ready_actions(self, plan_id: str) -> tuple[ActionRecord, ...]:
        """Return claimable read actions whose dependencies are satisfied."""


class ResourceRefRepository(Protocol):
    """Resource reference persistence."""

    def get_by_id(self, resource_ref_id: str) -> ResourceRefRecord | None:
        """Return one resource reference by identifier."""

    def get_by_unique_key(
        self,
        *,
        run_id: str,
        connector_id: str,
        resource_type: str,
        resource_id: str,
    ) -> ResourceRefRecord | None:
        """Return one resource reference by connector-aware unique key."""

    def upsert(self, record: ResourceRefRecord) -> None:
        """Insert or update one resource reference."""

    def list_by_run(self, run_id: str) -> tuple[ResourceRefRecord, ...]:
        """Return resource references for one run."""


class EvidenceRepository(Protocol):
    """Evidence persistence."""

    def insert(self, record: EvidenceRecord) -> None:
        """Persist one evidence row."""

    def link_to_action(self, *, action_id: str, evidence_id: str) -> None:
        """Link one evidence row to one action."""

    def list_by_action(self, action_id: str) -> tuple[EvidenceRecord, ...]:
        """Return evidence rows linked to one action."""


class ActionDependencyRepository(Protocol):
    """Action dependency persistence."""

    def add(self, *, action_id: str, depends_on_action_id: str) -> None:
        """Persist one dependency edge."""

    def list_dependencies(self, action_id: str) -> tuple[str, ...]:
        """Return action identifiers that the action depends on."""

    def list_dependents(self, action_id: str) -> tuple[str, ...]:
        """Return action identifiers that depend on the action."""


class AuditRepository(Protocol):
    """Append-only audit persistence."""

    def append(self, event: AuditEventRecord) -> None:
        """Append an audit event row."""

    def add(self, event: AuditEventRecord) -> None:
        """Append an audit event row."""

    def list_by_aggregate(
        self,
        *,
        run_id: str | None,
        action_id: str | None = None,
        cursor_after: int | None = None,
        limit: int = 100,
    ) -> tuple[PersistedAuditEventRecord, ...]:
        """Return audit rows for one aggregate using keyset pagination."""

    def list_after_cursor(
        self,
        *,
        cursor_after: int | None,
        limit: int = 100,
    ) -> tuple[PersistedAuditEventRecord, ...]:
        """Return audit rows after one cursor using keyset pagination."""

    def list_before_retention_cutoff(
        self,
        *,
        cutoff_ms: int,
        limit: int,
    ) -> tuple[PersistedAuditEventRecord, ...]:
        """Return audit rows eligible for retention purge."""

    def purge_before_cutoff(
        self,
        *,
        cutoff_ms: int,
        limit: int,
    ) -> int:
        """Delete at most `limit` audit rows older than the cutoff."""


class TraceRepository(Protocol):
    """Append-only trace persistence."""

    def append(self, event: TraceEventRecord) -> None:
        """Append a trace event row."""

    def add(self, event: TraceEventRecord) -> None:
        """Append a trace event row."""

    def list_by_run_after_cursor(
        self,
        *,
        run_id: str,
        cursor_after: int | None,
        limit: int = 100,
    ) -> tuple[PersistedTraceEventRecord, ...]:
        """Return trace rows for one run using keyset pagination."""

    def list_before_retention_cutoff(
        self,
        *,
        cutoff_ms: int,
        limit: int,
    ) -> tuple[PersistedTraceEventRecord, ...]:
        """Return trace rows eligible for retention purge."""

    def purge_before_cutoff(
        self,
        *,
        cutoff_ms: int,
        limit: int,
    ) -> int:
        """Delete at most `limit` trace rows older than the cutoff."""


class ApprovalRepository(Protocol):
    """Approval persistence."""

    def get_by_id(self, approval_id: str) -> ApprovalRecord | None:
        """Return an approval by identifier."""

    def get_active_by_action(self, action_id: str) -> ApprovalRecord | None:
        """Return the active approval for one action, if present."""

    def insert(self, record: ApprovalRecord) -> None:
        """Persist one approval row."""

    def mark_consumed(self, approval_id: str, *, consumed_at_ms: int) -> None:
        """Mark one approval as consumed."""

    def revoke_active_by_action(self, action_id: str) -> tuple[str, ...]:
        """Revoke active approvals for one action and return revoked ids."""

    def list_by_action(self, action_id: str) -> tuple[ApprovalRecord, ...]:
        """Return approvals for one action."""


class ExecutionAttemptRepository(Protocol):
    """Execution attempt persistence."""

    def get_by_id(self, attempt_id: str) -> ExecutionAttemptRecord | None:
        """Return an execution attempt by identifier."""

    def get_active_by_approval(self, approval_id: str) -> ExecutionAttemptRecord | None:
        """Return the active execution attempt for one approval, if present."""

    def insert_claimed(self, record: ExecutionAttemptRecord) -> None:
        """Persist one newly claimed execution attempt."""

    def mark_succeeded(
        self,
        attempt_id: str,
        *,
        expected_version: int,
        result_resource_ref_id: str | None,
        response_metadata_json: str | None,
        finished_at_ms: int,
    ) -> ExecutionAttemptRecord:
        """Mark one attempt as succeeded."""

    def mark_failed(
        self,
        attempt_id: str,
        *,
        expected_version: int,
        error_code: str,
        error_detail_json: str,
        finished_at_ms: int,
    ) -> ExecutionAttemptRecord:
        """Mark one attempt as failed."""

    def mark_unknown_result(
        self,
        attempt_id: str,
        *,
        expected_version: int,
        error_code: str,
        error_detail_json: str,
        finished_at_ms: int,
    ) -> ExecutionAttemptRecord:
        """Mark one attempt as UNKNOWN_RESULT."""

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
        """Persist one arbitrary terminal attempt status transition."""

    def list_by_approval(self, approval_id: str) -> tuple[ExecutionAttemptRecord, ...]:
        """Return attempts for one approval."""


class VerificationRepository(Protocol):
    """Verification persistence."""

    def insert(self, record: VerificationRecord) -> None:
        """Persist one verification row."""

    def list_by_attempt(self, execution_attempt_id: str) -> tuple[VerificationRecord, ...]:
        """Return verifications for one attempt."""


class UnitOfWork(AbstractContextManager["UnitOfWork"], Protocol):
    """Transactional repository bundle."""

    conversations: ConversationRepository
    runs: RunRepository
    messages: MessageRepository
    command_receipts: CommandReceiptRepository
    plans: PlanRepository
    actions: ActionRepository
    resource_refs: ResourceRefRepository
    evidence: EvidenceRepository
    action_dependencies: ActionDependencyRepository
    approvals: ApprovalRepository
    execution_attempts: ExecutionAttemptRepository
    verifications: VerificationRepository
    audits: AuditRepository
    traces: TraceRepository

    def commit(self) -> None:
        """Commit the current transaction."""

    def rollback(self) -> None:
        """Rollback the current transaction."""
