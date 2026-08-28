"""Project current durable Evidence and context-adjustment eligibility."""

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.checkpoint_port import CheckpointPort


@dataclass(frozen=True, slots=True)
class ProjectContextPreviewQueryV1:
    run_id: str


@dataclass(frozen=True, slots=True)
class ContextPreviewItemV1:
    segment_id: str
    resource_ref_id: str | None
    resource_type: str
    excerpt: str


@dataclass(frozen=True, slots=True)
class ProjectContextPreviewResultV1:
    run_id: str
    retrieval_revision: int
    items: tuple[ContextPreviewItemV1, ...]
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
            plan = max(plans, key=lambda item: item.revision_no, default=None)
            actions = () if plan is None else unit_of_work.actions.list_for_plan(plan.id)
            approvals = () if plan is None else unit_of_work.approvals.list_active_for_plan(plan.id)
            evidence = unit_of_work.evidence.list_for_run(query.run_id, limit=self._max_items)
            has_inflight = any(
                attempt is not None
                for action in actions
                for approval in (unit_of_work.approvals.get_active_for_action(action.id),)
                if approval is not None
                for attempt in (
                    unit_of_work.execution_attempts.get_active_for_approval(approval.id),
                )
            )
        allowed = (
            run.status is RunStatusV1.WAITING_APPROVAL
            and plan is not None
            and all(
                action.status in {ActionStatusV1.PROPOSED.value, ActionStatusV1.MODIFIED.value}
                for action in actions
            )
            and not approvals
            and not has_inflight
        )
        items = tuple(
            ContextPreviewItemV1(
                segment_id=item.id,
                resource_ref_id=item.resource_ref_id,
                resource_type=item.kind,
                excerpt=item.excerpt[: self._max_excerpt_chars],
            )
            for item in evidence
        )
        return ProjectContextPreviewResultV1(
            query.run_id,
            head.retrieval_revision,
            items,
            allowed,
            ("EXCLUDE_EVIDENCE", "RETRIEVE_MORE") if allowed else (),
        )


__all__ = [
    "ContextPreviewItemV1",
    "ProjectContextPreviewHandler",
    "ProjectContextPreviewQueryV1",
    "ProjectContextPreviewResultV1",
]
