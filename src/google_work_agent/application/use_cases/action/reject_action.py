"""Canonical Application owner for Action rejection."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol, cast

from google_work_agent.application.projections import build_snapshot_required_event
from google_work_agent.application.write_action_mutation_contracts import RejectWriteActionCommand
from google_work_agent.ports import Clock, RunEventPublisher, UnitOfWork


class _RejectService(Protocol):
    def __call__(self, command: RejectWriteActionCommand) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class RejectActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    expected_version: int
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class RejectActionResult:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    conflict_detail: str | None = None


class RejectActionHandler:
    def __init__(
        self,
        *,
        reject_service: _RejectService,
        unit_of_work_factory: Callable[[], UnitOfWork],
        event_publisher: RunEventPublisher,
        clock: Clock,
    ) -> None:
        self._reject_service = reject_service
        self._unit_of_work_factory = unit_of_work_factory
        self._event_publisher = event_publisher
        self._clock = clock

    def __call__(self, command: RejectActionCommand) -> RejectActionResult:
        actor_account_id, run_id = self._account_and_run_id(command.action_id)
        raw = self._reject_service(
            RejectWriteActionCommand(
                command_id=command.command_id,
                request_hash=command.request_hash,
                action_id=command.action_id,
                expected_version=command.expected_version,
                actor_account_id=actor_account_id,
                reason_code=command.reason_code,
            )
        )
        result = RejectActionResult(
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
        if result.applied:
            self._event_publisher.publish(
                build_snapshot_required_event(
                    run_id=run_id,
                    occurred_at_ms=self._clock.now_ms(),
                    reason="ACTION_REJECTED",
                )
            )
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
