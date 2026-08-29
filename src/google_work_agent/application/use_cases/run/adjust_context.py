"""Validate and apply one current-Run context adjustment."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.application.use_cases.run.begin_planning import (
    BeginPlanningCommand,
    BeginPlanningHandler,
)
from google_work_agent.application.use_cases.run.project_context_preview import (
    ProjectContextPreviewHandler,
    ProjectContextPreviewQueryV1,
)
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
    ScheduleRunExecutionHandler,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_handoff import ContextAdjustmentControlV1

MAX_REQUESTED_INFORMATION_CHARS = 2048


@dataclass(frozen=True, slots=True)
class AdjustContextCommandV1:
    schema_version: int
    command_id: str
    run_id: str
    expected_version: int
    expected_retrieval_revision: int
    adjustment_kind: str
    segment_ids: tuple[str, ...] | None = None
    requested_information: str | None = None


@dataclass(frozen=True, slots=True)
class AdjustContextResultV1:
    schema_version: int
    accepted: bool
    current_version: int
    next_phase: str | None


class AdjustContextHandler:
    """Own current identity/membership checks and delegate lifecycle mutation."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        project_context_preview: ProjectContextPreviewHandler,
        begin_planning: BeginPlanningHandler,
        schedule_run_execution: ScheduleRunExecutionHandler,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._project_context_preview = project_context_preview
        self._begin_planning = begin_planning
        self._schedule_run_execution = schedule_run_execution

    def __call__(self, command: AdjustContextCommandV1) -> AdjustContextResultV1:
        adjustment = _validated_adjustment(command)
        run_version, plan_id = self._current_run_and_plan(command.run_id)
        if run_version != command.expected_version:
            return AdjustContextResultV1(1, False, run_version, None)

        preview = self._project_context_preview(ProjectContextPreviewQueryV1(command.run_id))
        if (
            preview.retrieval_revision != command.expected_retrieval_revision
            or not preview.adjustment_allowed
        ):
            return AdjustContextResultV1(1, False, run_version, None)
        if command.adjustment_kind == "EXCLUDE_EVIDENCE":
            current_ids = {item.segment_id for item in preview.items}
            assert command.segment_ids is not None
            if not set(command.segment_ids).issubset(current_ids):
                return AdjustContextResultV1(1, False, run_version, None)

        request_hash = calculate_canonical_json_hash(
            {
                "run_id": command.run_id,
                "plan_id": plan_id,
                "expected_version": command.expected_version,
                "expected_retrieval_revision": command.expected_retrieval_revision,
                "adjustment": adjustment,
            }
        )
        result = self._begin_planning(
            BeginPlanningCommand(
                run_id=command.run_id,
                expected_version=command.expected_version,
                command_id=command.command_id,
                request_hash=request_hash,
                plan_id=plan_id,
                expected_retrieval_revision=command.expected_retrieval_revision,
                context_adjustment=ContextAdjustmentControlV1(
                    kind="CONTEXT_ADJUSTMENT", adjustment=adjustment
                ),
            )
        )
        if result.applied and result.handoff_id is not None:
            self._schedule_run_execution(ScheduleRunExecutionCommand(handoff_id=result.handoff_id))
        return AdjustContextResultV1(
            schema_version=1,
            accepted=result.applied,
            current_version=result.current_version,
            next_phase="RETRIEVAL" if result.applied else None,
        )

    def _current_run_and_plan(self, run_id: str) -> tuple[int, str]:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(run_id)
            if run is None:
                raise LookupError(f"run not found: {run_id}")
            plans = current_plan_tuple(unit_of_work.plans, run_id)
            plan = max(plans, key=lambda item: (item.revision_no, item.id), default=None)
            if plan is None or plan.status is not PlanStatusV1.WAITING_APPROVAL:
                return run.version, ""
            return run.version, plan.id


def _validated_adjustment(command: AdjustContextCommandV1) -> dict[str, object]:
    if command.schema_version != 1:
        raise ValueError("unsupported context-adjustment schema")
    segment_ids = () if command.segment_ids is None else command.segment_ids
    if len(segment_ids) != len(set(segment_ids)) or any(not item for item in segment_ids):
        raise ValueError("segment_ids must contain unique non-empty values")
    if command.adjustment_kind == "EXCLUDE_EVIDENCE":
        if not segment_ids or command.requested_information is not None:
            raise ValueError(
                "EXCLUDE_EVIDENCE requires segment_ids and forbids requested_information"
            )
        return {
            "kind": "EXCLUDE_EVIDENCE",
            "segment_ids": list(segment_ids),
            "requested_information": None,
        }
    if command.adjustment_kind != "RETRIEVE_MORE":
        raise ValueError("unsupported context adjustment")
    requested = " ".join((command.requested_information or "").split())
    if segment_ids or not requested or len(requested) > MAX_REQUESTED_INFORMATION_CHARS:
        raise ValueError(
            "RETRIEVE_MORE requires no segment_ids and bounded requested_information"
        )
    return {
        "kind": "RETRIEVE_MORE",
        "segment_ids": [],
        "requested_information": requested,
    }


__all__ = ["AdjustContextCommandV1", "AdjustContextHandler", "AdjustContextResultV1"]
