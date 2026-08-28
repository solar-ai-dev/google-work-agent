"""Validate and apply one current-Run context adjustment."""

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
from google_work_agent.ports.system.contracts.workflow_handoff import ContextAdjustmentControlV1


@dataclass(frozen=True, slots=True)
class AdjustContextCommandV1:
    schema_version: int
    command_id: str
    run_id: str
    plan_id: str
    expected_run_version: int
    expected_retrieval_revision: int
    adjustment_kind: str
    evidence_ids: tuple[str, ...] = ()
    retrieval_query: str | None = None


@dataclass(frozen=True, slots=True)
class AdjustContextResultV1:
    schema_version: int
    applied: bool
    result_code: str
    run_status: str
    run_version: int
    handoff_id: str | None
    conflict_detail: str | None = None


class AdjustContextHandler:
    """Own preview membership checks and delegate lifecycle mutation to BeginPlanning."""

    def __init__(
        self,
        *,
        project_context_preview: ProjectContextPreviewHandler,
        begin_planning: BeginPlanningHandler,
        schedule_run_execution: ScheduleRunExecutionHandler,
    ) -> None:
        self._project_context_preview = project_context_preview
        self._begin_planning = begin_planning
        self._schedule_run_execution = schedule_run_execution

    def __call__(self, command: AdjustContextCommandV1) -> AdjustContextResultV1:
        if command.schema_version != 1:
            raise ValueError("unsupported context-adjustment schema")
        if command.adjustment_kind not in {"EXCLUDE_EVIDENCE", "RETRIEVE_MORE"}:
            raise ValueError("unsupported context adjustment")
        if command.adjustment_kind == "EXCLUDE_EVIDENCE" and not command.evidence_ids:
            raise ValueError("EXCLUDE_EVIDENCE requires evidence_ids")
        if command.adjustment_kind == "RETRIEVE_MORE" and not command.retrieval_query:
            raise ValueError("RETRIEVE_MORE requires retrieval_query")

        preview = self._project_context_preview(ProjectContextPreviewQueryV1(command.run_id))
        if preview.retrieval_revision != command.expected_retrieval_revision:
            return AdjustContextResultV1(
                1,
                False,
                "VERSION_CONFLICT",
                "WAITING_APPROVAL",
                command.expected_run_version,
                None,
                "retrieval revision mismatch",
            )
        if not preview.adjustment_allowed:
            return AdjustContextResultV1(
                1,
                False,
                "STATE_CONFLICT",
                "WAITING_APPROVAL",
                command.expected_run_version,
                None,
                "context adjustment is not currently allowed",
            )
        current_ids = {item.segment_id for item in preview.items}
        if command.adjustment_kind == "EXCLUDE_EVIDENCE" and not set(command.evidence_ids).issubset(
            current_ids
        ):
            return AdjustContextResultV1(
                1,
                False,
                "STATE_CONFLICT",
                "WAITING_APPROVAL",
                command.expected_run_version,
                None,
                "excluded evidence is not in the current preview",
            )

        adjustment: dict[str, object] = {"kind": command.adjustment_kind}
        if command.evidence_ids:
            adjustment["evidence_ids"] = list(command.evidence_ids)
        if command.retrieval_query is not None:
            adjustment["retrieval_query"] = command.retrieval_query
        request_hash = calculate_canonical_json_hash(
            {
                "run_id": command.run_id,
                "plan_id": command.plan_id,
                "expected_run_version": command.expected_run_version,
                "expected_retrieval_revision": command.expected_retrieval_revision,
                "adjustment": adjustment,
            }
        )
        result = self._begin_planning(
            BeginPlanningCommand(
                run_id=command.run_id,
                expected_version=command.expected_run_version,
                command_id=command.command_id,
                request_hash=request_hash,
                plan_id=command.plan_id,
                expected_retrieval_revision=command.expected_retrieval_revision,
                context_adjustment=ContextAdjustmentControlV1(
                    kind="CONTEXT_ADJUSTMENT", adjustment=adjustment
                ),
            )
        )
        if result.applied and result.handoff_id is not None:
            self._schedule_run_execution(ScheduleRunExecutionCommand(handoff_id=result.handoff_id))
        return AdjustContextResultV1(
            1,
            result.applied,
            result.result_code,
            result.current_status,
            result.current_version,
            result.handoff_id,
            result.conflict_detail,
        )


__all__ = ["AdjustContextCommandV1", "AdjustContextHandler", "AdjustContextResultV1"]
