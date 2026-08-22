"""Canonical Application owner for Action modification."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol, cast

from google_work_agent.application.coordinator import LocalRunCoordinator, QueueBusyError
from google_work_agent.application.write_action_mutation_contracts import ModifyWriteActionCommand
from google_work_agent.ports import PlanReviewStatus, UnitOfWork


class _ModifyService(Protocol):
    def __call__(self, command: ModifyWriteActionCommand) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class ModifyActionCommand:
    command_id: str
    request_hash: str
    request_id: str
    action_id: str
    expected_version: int
    arguments_patch: dict[str, object]


@dataclass(frozen=True, slots=True)
class ModifyActionResult:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    conflict_detail: str | None = None


class ModifyActionFollowupQueueBusyError(RuntimeError):
    def __init__(self, *, current_state: str) -> None:
        super().__init__("modified action review is queued")
        self.current_state = current_state


class ModifyActionHandler:
    def __init__(
        self,
        *,
        modify_service: _ModifyService,
        unit_of_work_factory: Callable[[], UnitOfWork],
        local_run_coordinator: LocalRunCoordinator,
    ) -> None:
        self._modify_service = modify_service
        self._unit_of_work_factory = unit_of_work_factory
        self._local_run_coordinator = local_run_coordinator

    def __call__(self, command: ModifyActionCommand) -> ModifyActionResult:
        raw = self._modify_service(
            ModifyWriteActionCommand(
                command_id=command.command_id,
                request_hash=command.request_hash,
                action_id=command.action_id,
                expected_version=command.expected_version,
                arguments_patch=dict(command.arguments_patch),
            )
        )
        result = ModifyActionResult(
            applied=bool(raw["applied"]),
            result_code=str(raw["result_code"]),
            action_id=str(raw["action_id"]),
            action_status=str(raw["action_status"]),
            action_version=int(cast(int | str, raw["action_version"])),
            next_allowed_commands=tuple(
                str(item) for item in cast(Iterable[object], raw["next_allowed_commands"])
            ),
            conflict_detail=None if raw["conflict_detail"] is None else str(raw["conflict_detail"]),
        )
        if not result.applied:
            return result

        run_id, plan_id, review_status, review_version = self._review_context(command.action_id)
        if review_status is PlanReviewStatus.REQUIRED:
            try:
                self._local_run_coordinator.enqueue_resume(
                    run_id=run_id,
                    request_id=command.request_id,
                    command_id=command.command_id,
                    resume_kind="MODIFY_REVIEW",
                    resume_payload={
                        "resume_kind": "MODIFY_REVIEW",
                        "plan_id": plan_id,
                        "review_version": review_version,
                    },
                )
            except QueueBusyError as error:
                raise ModifyActionFollowupQueueBusyError(
                    current_state=result.action_status
                ) from error
        return result

    def _review_context(self, action_id: str) -> tuple[str, str, PlanReviewStatus, int]:
        with self._unit_of_work_factory() as unit_of_work:
            action = unit_of_work.actions.get_by_id(action_id)
            if action is None:
                raise LookupError(f"action not found: {action_id}")
            plan = unit_of_work.plans.get_by_id(action.plan_id)
            if plan is None:
                raise LookupError(f"plan not found: {action.plan_id}")
            return plan.run_id, plan.id, plan.review_status, plan.review_version
