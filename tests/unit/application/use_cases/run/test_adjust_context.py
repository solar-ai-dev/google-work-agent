from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from google_work_agent.application.use_cases.run.adjust_context import (
    AdjustContextCommandV1,
    AdjustContextHandler,
)
from google_work_agent.application.use_cases.run.begin_planning import (
    BeginPlanningCommand,
    BeginPlanningResult,
)
from google_work_agent.application.use_cases.run.project_context_preview import (
    ContextPreviewItemV1,
    ProjectContextPreviewResultV1,
)
from google_work_agent.domain.plan.model import Plan, PlanReviewStatus, PlanStatusV1
from google_work_agent.domain.run.model import Run, RunStatusV1
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


class _UnitOfWork:
    def __init__(self) -> None:
        self.runs = SimpleNamespace(get=lambda _run_id: _run())
        self.plans = SimpleNamespace(get_current=lambda _run_id: _plan())

    def __enter__(self) -> _UnitOfWork:
        return self

    def __exit__(self, *args: object) -> None:
        del args


def _run() -> Run:
    return Run(
        id="run-1",
        conversation_id="conversation-1",
        status=RunStatusV1.WAITING_APPROVAL,
        version=4,
        started_at_ms=1,
        finished_at_ms=None,
        entry_mode="AGENT_SEARCH",
        langgraph_thread_id="thread-1",
        requested_mode="AUTO",
        actual_runtime=None,
    )


def _plan() -> Plan:
    return Plan(
        "plan-server",
        "run-1",
        2,
        PlanStatusV1.WAITING_APPROVAL,
        "Plan",
        2,
        PlanReviewStatus.PASSED,
        1,
        "PASS",
    )


def _preview() -> ProjectContextPreviewResultV1:
    return ProjectContextPreviewResultV1(
        1,
        "run-1",
        7,
        (ContextPreviewItemV1("segment-1", "SUPPORTS", "tasks", "task", "1", "T", None),),
        0,
        1,
        0,
        True,
        ("EXCLUDE_EVIDENCE", "RETRIEVE_MORE"),
    )


def _command(**changes: object) -> AdjustContextCommandV1:
    values: dict[str, object] = {
        "schema_version": 1,
        "command_id": "adjust-1",
        "run_id": "run-1",
        "expected_version": 4,
        "expected_retrieval_revision": 7,
        "adjustment_kind": "EXCLUDE_EVIDENCE",
        "segment_ids": ("segment-1",),
    }
    values.update(changes)
    return AdjustContextCommandV1(**values)  # type: ignore[arg-type]


def test_stale_or__nonmember_adjustment__never_invokes_workflow() -> None:
    begin_calls: list[BeginPlanningCommand] = []
    schedule_calls: list[object] = []
    handler = AdjustContextHandler(
        unit_of_work_factory=lambda: cast(UnitOfWork, _UnitOfWork()),
        project_context_preview=lambda _query: _preview(),  # type: ignore[arg-type]
        begin_planning=lambda command: begin_calls.append(command),  # type: ignore[arg-type]
        schedule_run_execution=lambda command: schedule_calls.append(command),  # type: ignore[arg-type]
    )

    stale = handler(_command(expected_retrieval_revision=6))
    nonmember = handler(_command(segment_ids=("segment-old",)))

    assert stale.accepted is False
    assert nonmember.accepted is False
    assert begin_calls == schedule_calls == []


def test_current_selector__uses_server_plan__and_schedules_once() -> None:
    begin_calls: list[BeginPlanningCommand] = []
    schedule_calls: list[object] = []

    def begin(command: BeginPlanningCommand) -> BeginPlanningResult:
        begin_calls.append(command)
        return BeginPlanningResult(
            True,
            "TRANSITION_APPLIED",
            "RETRIEVING",
            5,
            (),
            handoff_id="h-1",
        )

    handler = AdjustContextHandler(
        unit_of_work_factory=lambda: cast(UnitOfWork, _UnitOfWork()),
        project_context_preview=lambda _query: _preview(),  # type: ignore[arg-type]
        begin_planning=begin,  # type: ignore[arg-type]
        schedule_run_execution=lambda command: schedule_calls.append(command),  # type: ignore[arg-type]
    )

    result = handler(_command())

    assert result.accepted is True
    assert result.next_phase == "RETRIEVAL"
    assert len(begin_calls) == len(schedule_calls) == 1
    assert begin_calls[0].plan_id == "plan-server"


@pytest.mark.parametrize(
    "command",
    (
        _command(segment_ids=()),
        _command(requested_information="not allowed"),
        _command(
            adjustment_kind="RETRIEVE_MORE",
            segment_ids=None,
            requested_information="   ",
        ),
    ),
)
def test_adjust_context__enforces_exact__discriminated_payload(
    command: AdjustContextCommandV1,
) -> None:
    handler = AdjustContextHandler(
        unit_of_work_factory=lambda: cast(UnitOfWork, _UnitOfWork()),
        project_context_preview=lambda _query: _preview(),  # type: ignore[arg-type]
        begin_planning=lambda _command: None,  # type: ignore[arg-type]
        schedule_run_execution=lambda _command: None,  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError):
        handler(command)
