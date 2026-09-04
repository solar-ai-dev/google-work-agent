"""Project deterministic Error UI actions from durable Run/Action facts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from google_work_agent.application.use_cases.execution_attempt.project_delivery_certainty import (
    project_latest_delivery_certainty,
)
from google_work_agent.application.use_cases.plan.persistence_projection import current_plan_tuple
from google_work_agent.application.use_cases.run.resume_confirmation import ResumeTargetValidator
from google_work_agent.application.use_cases.run.resume_safe_checkpoint import (
    safe_checkpoint_resume_is_allowed,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.checkpoint_port import CheckpointPort

type ErrorUiActionKindV1 = Literal[
    "PREPARE_RETRY",
    "REAUTHENTICATE_GOOGLE",
    "RESUME_SAFE_CHECKPOINT",
    "OPEN_SETTINGS",
    "OPEN_DIAGNOSTICS",
]


@dataclass(frozen=True, slots=True)
class ProjectErrorActionsQueryV1:
    run_id: str


@dataclass(frozen=True, slots=True)
class ErrorUiActionV1:
    kind: ErrorUiActionKindV1
    action_id: str | None = None
    resume_kind: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectErrorActionsResultV1:
    schema_version: int
    error_code: str
    message: str
    actions: tuple[ErrorUiActionV1, ...]


class ProjectErrorActionsHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        checkpoint_port: CheckpointPort,
        resume_target_registry: ResumeTargetValidator,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._checkpoint_port = checkpoint_port
        self._resume_target_registry = resume_target_registry

    def __call__(self, query: ProjectErrorActionsQueryV1) -> ProjectErrorActionsResultV1 | None:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(query.run_id)
            if run is None:
                raise LookupError(f"run not found: {query.run_id}")
            plans = current_plan_tuple(unit_of_work.plans, run.id)
            plan = max(plans, key=lambda item: (item.revision_no, item.id), default=None)
            actions = () if plan is None else unit_of_work.actions.list_for_plan(plan.id)
            korean = _uses_korean(_request_text(unit_of_work, run.id, run.conversation_id))

            retry_actions = tuple(
                ErrorUiActionV1("PREPARE_RETRY", action_id=action.id)
                for action in actions
                if action.status == ActionStatusV1.FAILED.value
                and project_latest_delivery_certainty(unit_of_work, action.id) == "NOT_SENT"
            )
            if run.status is RunStatusV1.REAUTH_REQUIRED:
                return ProjectErrorActionsResultV1(
                    1,
                    "GOOGLE_REAUTH_REQUIRED",
                    (
                        "Google 연결이 만료되어 작업을 계속하려면 재인증이 필요합니다. "
                        "같은 작업을 다시 보내지 않고 재연결 후 현재 결과부터 확인합니다."
                        if korean
                        else "Your Google connection expired. Reconnect to continue; the same "
                        "action will not be resent before the current result is checked."
                    ),
                    (
                        ErrorUiActionV1("REAUTHENTICATE_GOOGLE"),
                        ErrorUiActionV1("OPEN_SETTINGS"),
                        ErrorUiActionV1("OPEN_DIAGNOSTICS"),
                    ),
                )
            if retry_actions:
                return ProjectErrorActionsResultV1(
                    1,
                    "ACTION_NOT_SENT",
                    (
                        "일부 작업이 Google에 전달되기 전에 실패했습니다. "
                        "아직 적용되지 않은 항목만 다시 준비할 수 있습니다."
                        if korean
                        else "Some actions failed before reaching Google. Only the items that "
                        "were not applied can be prepared again."
                    ),
                    (*retry_actions, ErrorUiActionV1("OPEN_DIAGNOSTICS")),
                )
            if safe_checkpoint_resume_is_allowed(
                unit_of_work=unit_of_work,
                checkpoint_port=self._checkpoint_port,
                run=run,
                resume_target_registry=self._resume_target_registry,
            ):
                return ProjectErrorActionsResultV1(
                    1,
                    "SAFE_CHECKPOINT_RESUME_AVAILABLE",
                    (
                        "검증된 안전 지점이 있어 완료되지 않은 작업을 "
                        "그 위치부터 계속할 수 있습니다."
                        if korean
                        else "A validated safe checkpoint is available, so the unfinished work "
                        "can continue from there."
                    ),
                    (
                        ErrorUiActionV1(
                            "RESUME_SAFE_CHECKPOINT",
                            resume_kind="SAFE_CHECKPOINT_RESUME",
                        ),
                        ErrorUiActionV1("OPEN_DIAGNOSTICS"),
                    ),
                )
            if run.status is RunStatusV1.FAILED:
                return ProjectErrorActionsResultV1(
                    1,
                    "RUN_FAILED",
                    (
                        "요청을 완료하지 못했으며 성공으로 처리하지 않았습니다. "
                        "진단에서 실패 지점을 확인할 수 있습니다."
                        if korean
                        else "I could not complete the request and did not report it as a "
                        "success. You can inspect the failure point in diagnostics."
                    ),
                    (ErrorUiActionV1("OPEN_DIAGNOSTICS"),),
                )
        return None


def _request_text(unit_of_work: UnitOfWork, run_id: str, conversation_id: str) -> str | None:
    messages, _ = unit_of_work.messages.list_by_conversation_keyset(
        conversation_id=conversation_id,
        cursor=None,
        page_size=200,
    )
    message = next(
        (item for item in messages if item.run_id == run_id and item.role == "USER"),
        None,
    )
    return None if message is None else message.content


def _uses_korean(value: str | None) -> bool:
    return value is None or any("\uac00" <= character <= "\ud7a3" for character in value)


__all__ = [
    "ErrorUiActionV1",
    "ProjectErrorActionsHandler",
    "ProjectErrorActionsQueryV1",
    "ProjectErrorActionsResultV1",
]
