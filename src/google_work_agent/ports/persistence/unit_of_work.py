"""Transactional persistence boundary."""

from contextlib import AbstractContextManager
from typing import Protocol

from google_work_agent.ports.persistence.action_repository import ActionRepository
from google_work_agent.ports.persistence.approval_repository import ApprovalRepository
from google_work_agent.ports.persistence.audit_event_repository import AuditEventRepository
from google_work_agent.ports.persistence.command_receipt_repository import CommandReceiptRepository
from google_work_agent.ports.persistence.conversation_repository import ConversationRepository
from google_work_agent.ports.persistence.evidence_repository import EvidenceRepository
from google_work_agent.ports.persistence.execution_attempt_repository import (
    ExecutionAttemptRepository,
)
from google_work_agent.ports.persistence.message_repository import MessageRepository
from google_work_agent.ports.persistence.plan_repository import PlanRepository
from google_work_agent.ports.persistence.recovery_repository import RecoveryRepository
from google_work_agent.ports.persistence.resource_ref_repository import ResourceRefRepository
from google_work_agent.ports.persistence.retention_repository import RetentionRepository
from google_work_agent.ports.persistence.run_repository import RunRepository
from google_work_agent.ports.persistence.trace_event_repository import TraceEventRepository
from google_work_agent.ports.persistence.verification_repository import VerificationRepository
from google_work_agent.ports.persistence.workflow_handoff_repository import (
    WorkflowHandoffRepository,
)
from google_work_agent.ports.system.checkpoint_port import InitialWorkflowBindingPort


class UnitOfWork(AbstractContextManager["UnitOfWork"], Protocol):
    conversations: ConversationRepository
    runs: RunRepository
    messages: MessageRepository
    command_receipts: CommandReceiptRepository
    plans: PlanRepository
    actions: ActionRepository
    resource_refs: ResourceRefRepository
    evidence: EvidenceRepository
    approvals: ApprovalRepository
    execution_attempts: ExecutionAttemptRepository
    verifications: VerificationRepository
    audits: AuditEventRepository
    traces: TraceEventRepository
    workflow_handoffs: WorkflowHandoffRepository
    recovery_contexts: RecoveryRepository
    retention: RetentionRepository
    workflow_bindings: InitialWorkflowBindingPort

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
