"""Canonical Application owner for explicit Action approval."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from google_work_agent.application.coordinator import LocalRunCoordinator, QueueBusyError
from google_work_agent.application.write_actions import ApproveWriteActionCommand
from google_work_agent.domain import calculate_canonical_json_hash
from google_work_agent.ports import IdGenerator, UnitOfWork


class _ApproveService(Protocol):
    def __call__(self, command: ApproveWriteActionCommand) -> object: ...


@dataclass(frozen=True, slots=True)
class ApproveActionCommand:
    command_id: str
    request_hash: str
    request_id: str
    action_id: str
    expected_version: int
    duplicate_acknowledged: bool = False
    calendar_conflict_acknowledged: bool = False


@dataclass(frozen=True, slots=True)
class ApproveActionResult:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    conflict_detail: str | None = None


class ApproveActionFollowupQueueBusyError(RuntimeError):
    def __init__(self, *, current_state: str) -> None:
        super().__init__("approval runtime resume is queued")
        self.current_state = current_state


class ApproveActionHandler:
    """Bind the Local API approval intent to durable Action approval authority.

    Browser/route inputs stop at command/version/acknowledgement data. Account,
    run, approval id, idempotency key and approval TTL are derived server-side.
    """

    def __init__(
        self,
        *,
        approve_service: _ApproveService,
        get_approval_ttl_minutes: Callable[[], int],
        unit_of_work_factory: Callable[[], UnitOfWork],
        local_run_coordinator: LocalRunCoordinator,
        id_generator: IdGenerator,
    ) -> None:
        self._approve_service = approve_service
        self._get_approval_ttl_minutes = get_approval_ttl_minutes
        self._unit_of_work_factory = unit_of_work_factory
        self._local_run_coordinator = local_run_coordinator
        self._id_generator = id_generator

    def __call__(self, command: ApproveActionCommand) -> ApproveActionResult:
        approved_by_account_id, run_id = self._account_and_run_id(command.action_id)
        ttl_ms = self._get_approval_ttl_minutes() * 60_000
        if ttl_ms <= 0:
            raise RuntimeError("approval_ttl_minutes must be positive")

        legacy_result = self._approve_service(
            ApproveWriteActionCommand(
                command_id=command.command_id,
                request_hash=command.request_hash,
                action_id=command.action_id,
                expected_version=command.expected_version,
                approved_by_account_id=approved_by_account_id,
                approved_by_display=None,
                source_snapshot={},
                approval_id=self._id_generator.next_id(),
                idempotency_key=calculate_canonical_json_hash(
                    {
                        "operation": "ApproveActionIdempotencyKeyV1",
                        "payload": {
                            "action_id": command.action_id,
                            "command_id": command.command_id,
                        },
                    }
                ),
                ttl_ms=ttl_ms,
                duplicate_acknowledged=command.duplicate_acknowledged,
                calendar_conflict_acknowledged=command.calendar_conflict_acknowledged,
            )
        )
        result = ApproveActionResult(
            applied=bool(getattr(legacy_result, "applied")),
            result_code=str(getattr(legacy_result, "result_code")),
            action_id=str(getattr(legacy_result, "action_id")),
            action_status=str(getattr(legacy_result, "action_status")),
            action_version=int(getattr(legacy_result, "action_version")),
            next_allowed_commands=tuple(getattr(legacy_result, "next_allowed_commands")),
            conflict_detail=getattr(legacy_result, "conflict_detail"),
        )
        if result.applied:
            try:
                self._local_run_coordinator.enqueue_resume(
                    run_id=run_id,
                    request_id=command.request_id,
                    command_id=command.command_id,
                    resume_kind="APPROVAL",
                    resume_payload={"approved": True},
                )
            except QueueBusyError as error:
                raise ApproveActionFollowupQueueBusyError(
                    current_state=result.action_status
                ) from error
        return result

    def _account_and_run_id(self, action_id: str) -> tuple[str, str]:
        with self._unit_of_work_factory() as unit_of_work:
            action = unit_of_work.actions.get_by_id(action_id)
            if action is None:
                raise LookupError(f"action not found: {action_id}")
            plan = unit_of_work.plans.get_by_id(action.plan_id)
            if plan is None:
                raise LookupError(f"plan not found: {action.plan_id}")
            run = unit_of_work.runs.get_by_id(plan.run_id)
            if run is None:
                raise LookupError(f"run not found: {plan.run_id}")
            conversation = unit_of_work.conversations.get_by_id(run.conversation_id)
            if conversation is None:
                raise LookupError(f"conversation not found: {run.conversation_id}")
            return conversation.account_id, run.id
