"""Persistence boundary for the durable workflow handoff outbox."""

from typing import Protocol

from google_work_agent.ports.system.contracts.workflow_handoff import (
    WorkflowExecutionAdmissionV1,
    WorkflowExecutionReleaseReasonV1,
    WorkflowExecutionSettlementV1,
    WorkflowHandoffStageV1,
    WorkflowHandoffV1,
)


class WorkflowHandoffRepository(Protocol):
    def stage_pending(self, stage: WorkflowHandoffStageV1) -> WorkflowHandoffV1: ...
    def get(self, handoff_id: str) -> WorkflowHandoffV1 | None: ...
    def get_by_trigger_command_id(self, trigger_command_id: str) -> WorkflowHandoffV1 | None: ...
    def get_dispatch_head(self, run_id: str) -> WorkflowHandoffV1 | None: ...
    def list_redriveable(self, limit: int) -> list[WorkflowHandoffV1]: ...

    def list_blocked_binding(self, limit: int) -> list[WorkflowHandoffV1]: ...
    def claim_execution_admission(
        self, handoff_id: str, expected_version: int, admission: WorkflowExecutionAdmissionV1
    ) -> WorkflowHandoffV1: ...
    def release_execution_admission(
        self,
        handoff_id: str,
        expected_version: int,
        admission_id: str,
        reason_code: WorkflowExecutionReleaseReasonV1,
    ) -> WorkflowHandoffV1: ...
    def mark_consumed_and_clear_payload(
        self,
        handoff_id: str,
        expected_version: int,
        admission_id: str,
        applied_checkpoint_id: str,
        applied_checkpoint_generation: int,
    ) -> WorkflowExecutionSettlementV1: ...
    def complete_recovery_admission(
        self,
        handoff_id: str,
        expected_version: int,
        admission_id: str,
        admission_checkpoint_id: str,
        admission_checkpoint_generation: int,
    ) -> WorkflowExecutionSettlementV1: ...
    def mark_superseded(
        self, handoff_id: str, expected_version: int, reason_code: str
    ) -> WorkflowHandoffV1: ...
    def supersede_unconsumed_for_run(
        self, run_id: str, reason_code: str
    ) -> list[WorkflowHandoffV1]: ...
