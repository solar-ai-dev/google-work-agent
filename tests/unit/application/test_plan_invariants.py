from dataclasses import dataclass

import pytest

from google_work_agent.application.plan_invariants import validate_plan_structure
from google_work_agent.application.write_plan import validate_write_plan
from google_work_agent.application.write_plan_contracts import (
    SaveWritePlanCommand,
    WriteActionDraft,
    WriteEvidenceDraft,
)
from google_work_agent.domain import PolicyViolationError, build_p0_tool_registry
from google_work_agent.ports import EvidenceOriginType


@dataclass(frozen=True)
class _Evidence:
    evidence_id: str


@dataclass(frozen=True)
class _Action:
    action_id: str
    position: int
    evidence_ids: tuple[str, ...]
    depends_on_action_ids: tuple[str, ...] = ()


def test_shared_plan_structure_rejects_zero_evidence_action() -> None:
    with pytest.raises(ValueError, match="action requires evidence"):
        validate_plan_structure(
            actions=(_Action("action-1", 1, ()),),
            evidence=(_Evidence("evidence-1"),),
            plan_label="write plan",
        )


def test_shared_plan_structure_rejects_missing_evidence_and_dependency_cycle() -> None:
    with pytest.raises(LookupError, match="action references missing evidence"):
        validate_plan_structure(
            actions=(_Action("action-1", 1, ("missing",)),),
            evidence=(_Evidence("evidence-1"),),
            plan_label="write plan",
        )

    with pytest.raises(ValueError, match="action dependency cycle detected"):
        validate_plan_structure(
            actions=(
                _Action("action-1", 1, ("evidence-1",), ("action-2",)),
                _Action("action-2", 2, ("evidence-1",), ("action-1",)),
            ),
            evidence=(_Evidence("evidence-1"),),
            plan_label="read-only plan",
        )


def test_write_plan_evidence_policy_counts_each_actions_links_not_plan_total() -> None:
    evidence = (
        WriteEvidenceDraft(
            evidence_id="evidence-1",
            origin_type=EvidenceOriginType.DERIVED,
            kind="USER_REQUEST",
            excerpt="Update the selected task.",
        ),
        WriteEvidenceDraft(
            evidence_id="evidence-2",
            origin_type=EvidenceOriginType.DERIVED,
            kind="CONTEXT",
            excerpt="Second plan-level evidence not linked to this action.",
        ),
    )
    command = SaveWritePlanCommand(
        command_id="command-1",
        request_hash="a" * 64,
        plan_id="plan-1",
        run_id="run-1",
        revision_no=1,
        summary_text="Update one task",
        expected_run_version=0,
        actions=(
            WriteActionDraft(
                action_id="action-1",
                position=1,
                tool_name="tasks_update_task",
                arguments={"task_id": "task-1", "title": "Updated"},
                expected={"resource_type": "TASK"},
                evidence_ids=("evidence-1",),
            ),
        ),
        evidence=evidence,
    )

    with pytest.raises(
        PolicyViolationError,
        match="existing resource updates require a user-selected target, two evidences",
    ):
        validate_write_plan(command, build_p0_tool_registry())


def test_write_plan_accepts_two_action_linked_evidences_for_unselected_update() -> None:
    evidence = (
        WriteEvidenceDraft(
            evidence_id="evidence-1",
            origin_type=EvidenceOriginType.DERIVED,
            kind="USER_REQUEST",
            excerpt="Update the task.",
        ),
        WriteEvidenceDraft(
            evidence_id="evidence-2",
            origin_type=EvidenceOriginType.DERIVED,
            kind="CONTEXT",
            excerpt="Confirmed task identity.",
        ),
    )
    command = SaveWritePlanCommand(
        command_id="command-2",
        request_hash="b" * 64,
        plan_id="plan-2",
        run_id="run-2",
        revision_no=1,
        summary_text="Update one task",
        expected_run_version=0,
        actions=(
            WriteActionDraft(
                action_id="action-2",
                position=1,
                tool_name="tasks_update_task",
                arguments={"task_id": "task-1", "title": "Updated"},
                expected={"resource_type": "TASK"},
                evidence_ids=("evidence-1", "evidence-2"),
            ),
        ),
        evidence=evidence,
    )

    validate_write_plan(command, build_p0_tool_registry())
