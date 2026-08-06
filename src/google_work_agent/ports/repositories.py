"""Repository and transaction port definitions."""

from contextlib import AbstractContextManager
from typing import Protocol

from google_work_agent.domain import (
    ActionCommand,
    ActionStatus,
    CommandResult,
    ResultCode,
    RunCommand,
    RunStatus,
)
from google_work_agent.ports.models import (
    ActionRecord,
    AnswerOnlyResponse,
    AuditEventRecord,
    CommandReceiptRecord,
    ConversationRecord,
    EvidenceRecord,
    MessageRecord,
    PlanRecord,
    ResourceRefRecord,
    RunRecord,
    TraceEventRecord,
)


class ConversationRepository(Protocol):
    """Conversation access required by product-core application services."""

    def get_by_id(self, conversation_id: str) -> ConversationRecord | None:
        """Return a conversation by identifier."""


class RunRepository(Protocol):
    """Run access and state transition persistence."""

    def get_by_id(self, run_id: str) -> RunRecord | None:
        """Return a run by identifier."""

    def complete_answer_only_run(
        self,
        run_id: str,
        *,
        expected_version: int,
        finished_at_ms: int,
    ) -> CommandResult[RunStatus, RunCommand]:
        """Complete a run through the answer-only transition path."""

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

    def activate(self, plan_id: str) -> None:
        """Promote a draft plan to ACTIVE."""

    def complete(self, plan_id: str) -> None:
        """Mark a plan as COMPLETED."""

    def list_by_run(self, run_id: str) -> tuple[PlanRecord, ...]:
        """Return plans for one run."""


class ActionRepository(Protocol):
    """Read-only action persistence."""

    def get_by_id(self, action_id: str) -> ActionRecord | None:
        """Return an action by identifier."""

    def insert_read_action(self, action: ActionRecord) -> None:
        """Persist a new read action."""

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

    def mark_dependency_blocked(self, action_id: str, *, updated_at_ms: int) -> bool:
        """Mark one action as dependency blocked when still PROPOSED."""

    def list_by_plan(self, plan_id: str) -> tuple[ActionRecord, ...]:
        """Return actions for one plan."""

    def list_ready_actions(self, plan_id: str) -> tuple[ActionRecord, ...]:
        """Return claimable read actions whose dependencies are satisfied."""


class ResourceRefRepository(Protocol):
    """Resource reference persistence."""

    def get_by_unique_key(
        self,
        *,
        run_id: str,
        source: str,
        resource_type: str,
        resource_id: str,
    ) -> ResourceRefRecord | None:
        """Return one resource reference by unique key."""

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


class AuditRepository(Protocol):
    """Append-only audit persistence."""

    def add(self, event: AuditEventRecord) -> None:
        """Append an audit event row."""


class TraceRepository(Protocol):
    """Append-only trace persistence."""

    def add(self, event: TraceEventRecord) -> None:
        """Append a trace event row."""


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
    audits: AuditRepository
    traces: TraceRepository

    def commit(self) -> None:
        """Commit the current transaction."""

    def rollback(self) -> None:
        """Rollback the current transaction."""
