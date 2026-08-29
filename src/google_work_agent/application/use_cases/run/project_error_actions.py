"""Project deterministic Error UI actions from durable Run/Action facts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from json import JSONDecodeError, loads
from typing import Literal

from google_work_agent.application.use_cases.run.resume_confirmation import ResumeTargetValidator
from google_work_agent.application.use_cases.run.resume_safe_checkpoint import (
    safe_checkpoint_resume_is_allowed,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import (
    ExecutionAttempt,
    ExecutionAttemptStatusV1,
)
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

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
        resume_target_registry: ResumeTargetValidator,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._resume_target_registry = resume_target_registry

    def __call__(
        self, query: ProjectErrorActionsQueryV1
    ) -> ProjectErrorActionsResultV1 | None:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(query.run_id)
            if run is None:
                raise LookupError(f"run not found: {query.run_id}")
            plans = current_plan_tuple(unit_of_work.plans, run.id)
            plan = max(plans, key=lambda item: (item.revision_no, item.id), default=None)
            actions = () if plan is None else unit_of_work.actions.list_for_plan(plan.id)

            retry_actions = tuple(
                ErrorUiActionV1("PREPARE_RETRY", action_id=action.id)
                for action in actions
                if action.status == ActionStatusV1.FAILED.value
                and _latest_delivery_certainty(unit_of_work, action.id) == "NOT_SENT"
            )
            if run.status is RunStatusV1.REAUTH_REQUIRED:
                return ProjectErrorActionsResultV1(
                    1,
                    "GOOGLE_REAUTH_REQUIRED",
                    "Google authentication must be restored before this run can continue.",
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
                    "One or more actions failed before provider delivery.",
                    (*retry_actions, ErrorUiActionV1("OPEN_DIAGNOSTICS")),
                )
            if safe_checkpoint_resume_is_allowed(
                unit_of_work=unit_of_work,
                run=run,
                resume_target_registry=self._resume_target_registry,
            ):
                return ProjectErrorActionsResultV1(
                    1,
                    "SAFE_CHECKPOINT_RESUME_AVAILABLE",
                    "This run can continue from its validated safe checkpoint.",
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
                    "The run failed.",
                    (ErrorUiActionV1("OPEN_DIAGNOSTICS"),),
                )
        return None


def _latest_delivery_certainty(unit_of_work: UnitOfWork, action_id: str) -> str | None:
    latest: tuple[int, int, ExecutionAttempt] | None = None
    for approval in unit_of_work.approval_history.list_for_action(action_id):
        attempt = unit_of_work.execution_attempts.get_latest_for_approval(approval.id)
        if attempt is None:
            continue
        candidate = (approval.approval_no, attempt.attempt_no, attempt)
        if latest is None or candidate[:2] > latest[:2]:
            latest = candidate
    if latest is None:
        return None
    attempt = latest[2]
    if attempt.status is not ExecutionAttemptStatusV1.FAILED:
        return None
    raw = attempt.response_metadata_json
    if not isinstance(raw, str):
        return None
    try:
        metadata = loads(raw)
    except (JSONDecodeError, TypeError):
        return None
    if not isinstance(metadata, dict):
        return None
    certainty = metadata.get("delivery_certainty")
    return certainty if isinstance(certainty, str) else None


__all__ = [
    "ErrorUiActionV1",
    "ProjectErrorActionsHandler",
    "ProjectErrorActionsQueryV1",
    "ProjectErrorActionsResultV1",
]
