"""Project the current Retrieval selection and context-adjustment eligibility."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from json import JSONDecodeError, loads
from typing import Literal, cast

from google_work_agent.domain.action.model import Action, ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.checkpoint_port import CheckpointPort

type ContextRoleV1 = Literal["SUPPORTS", "CONTRADICTS", "CONTEXT"]
type ContextSourceV1 = Literal["gmail", "tasks", "calendar"]


@dataclass(frozen=True, slots=True)
class ProjectContextPreviewQueryV1:
    run_id: str


@dataclass(frozen=True, slots=True)
class ContextPreviewItemV1:
    segment_id: str
    role: ContextRoleV1
    source: ContextSourceV1
    resource_type: str
    resource_id: str
    display_label: str
    excerpt: str | None


@dataclass(frozen=True, slots=True)
class ProjectContextPreviewResultV1:
    schema_version: int
    run_id: str
    retrieval_revision: int
    items: tuple[ContextPreviewItemV1, ...]
    gmail_count: int
    tasks_count: int
    calendar_count: int
    adjustment_allowed: bool
    allowed_adjustments: tuple[str, ...]


class ProjectContextPreviewHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        checkpoint: CheckpointPort,
        max_items: int = 100,
        max_excerpt_chars: int = 500,
    ) -> None:
        if not 1 <= max_items <= 100:
            raise ValueError("context preview max_items must be between 1 and 100")
        if max_excerpt_chars < 1:
            raise ValueError("context preview max_excerpt_chars must be positive")
        self._unit_of_work_factory = unit_of_work_factory
        self._checkpoint = checkpoint
        self._max_items = max_items
        self._max_excerpt_chars = max_excerpt_chars

    def __call__(self, query: ProjectContextPreviewQueryV1) -> ProjectContextPreviewResultV1:
        head = self._checkpoint.load_retrieval_head(query.run_id)
        if head is None:
            raise LookupError("current RetrievalHeadV1 is unavailable")
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(query.run_id)
            if run is None:
                raise LookupError(f"run not found: {query.run_id}")
            plans = current_plan_tuple(unit_of_work.plans, query.run_id)
            plan = max(plans, key=lambda item: (item.revision_no, item.id), default=None)
            actions = () if plan is None else unit_of_work.actions.list_for_plan(plan.id)
            evidence = unit_of_work.evidence.list_for_retrieval_artifact(
                query.run_id,
                head.retrieval_artifact_id,
                limit=self._max_items,
            )
            items = tuple(
                item
                for record in evidence
                if (item := _preview_item(
                    unit_of_work=unit_of_work,
                    retrieval_artifact_id=head.retrieval_artifact_id,
                    record=record,
                    max_excerpt_chars=self._max_excerpt_chars,
                ))
                is not None
            )
            allowed = _adjustment_allowed(
                unit_of_work=unit_of_work,
                run_status=run.status,
                plan_id=None if plan is None else plan.id,
                actions=actions,
            )

        counts = {"gmail": 0, "tasks": 0, "calendar": 0}
        for item in items:
            counts[item.source] += 1
        return ProjectContextPreviewResultV1(
            schema_version=1,
            run_id=query.run_id,
            retrieval_revision=head.retrieval_revision,
            items=items,
            gmail_count=counts["gmail"],
            tasks_count=counts["tasks"],
            calendar_count=counts["calendar"],
            adjustment_allowed=allowed,
            allowed_adjustments=("EXCLUDE_EVIDENCE", "RETRIEVE_MORE") if allowed else (),
        )


def _preview_item(
    *,
    unit_of_work: UnitOfWork,
    retrieval_artifact_id: str,
    record: object,
    max_excerpt_chars: int,
) -> ContextPreviewItemV1 | None:
    locator_json = getattr(record, "locator_json", None)
    if not isinstance(locator_json, str):
        return None
    try:
        locator = loads(locator_json)
    except (JSONDecodeError, TypeError):
        return None
    if (
        not isinstance(locator, dict)
        or locator.get("retrieval_artifact_id") != retrieval_artifact_id
    ):
        return None
    segment_id = locator.get("segment_id")
    role = locator.get("role")
    resource_ref_id = getattr(record, "resource_ref_id", None)
    if (
        not isinstance(segment_id, str)
        or not segment_id
        or role not in {"SUPPORTS", "CONTRADICTS", "CONTEXT"}
        or not isinstance(resource_ref_id, str)
    ):
        return None
    resource = unit_of_work.resource_refs.get(resource_ref_id)
    if resource is None or resource.run_id != getattr(record, "run_id", None):
        return None
    source = _source_for_resource_type(resource.resource_type)
    excerpt = getattr(record, "excerpt", None)
    return ContextPreviewItemV1(
        segment_id=segment_id,
        role=cast(ContextRoleV1, role),
        source=source,
        resource_type=resource.resource_type,
        resource_id=resource.resource_id,
        display_label=resource.title or resource.resource_id,
        excerpt=(
            None
            if not isinstance(excerpt, str) or not excerpt
            else excerpt[:max_excerpt_chars]
        ),
    )


def _source_for_resource_type(resource_type: str) -> ContextSourceV1:
    if resource_type.startswith("gmail_"):
        return "gmail"
    if resource_type in {"task", "task_list"}:
        return "tasks"
    if resource_type in {"calendar", "calendar_event", "calendar_freebusy"}:
        return "calendar"
    raise ValueError(f"unsupported context resource type: {resource_type}")


def _adjustment_allowed(
    *,
    unit_of_work: UnitOfWork,
    run_status: RunStatusV1,
    plan_id: str | None,
    actions: tuple[Action, ...],
) -> bool:
    if (
        run_status is not RunStatusV1.WAITING_APPROVAL
        or plan_id is None
        or not actions
        or any(
            getattr(action, "status", None)
            not in {ActionStatusV1.PROPOSED.value, ActionStatusV1.MODIFIED.value}
            for action in actions
        )
        or unit_of_work.approvals.list_active_for_plan(plan_id)
    ):
        return False
    for action in actions:
        for approval in unit_of_work.approval_history.list_for_action(action.id):
            attempt = unit_of_work.execution_attempts.get_latest_for_approval(approval.id)
            if attempt is None:
                continue
            if attempt.status in {
                ExecutionAttemptStatusV1.CLAIMED,
                ExecutionAttemptStatusV1.EXECUTING,
                ExecutionAttemptStatusV1.UNKNOWN_RESULT,
            }:
                return False
            if (
                attempt.status is ExecutionAttemptStatusV1.SUCCEEDED
                and unit_of_work.verifications.get_latest_for_attempt(attempt.id) is None
            ):
                return False
    return True


__all__ = [
    "ContextPreviewItemV1",
    "ProjectContextPreviewHandler",
    "ProjectContextPreviewQueryV1",
    "ProjectContextPreviewResultV1",
]
