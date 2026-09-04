from __future__ import annotations

import pytest

from google_work_agent.adapters.langgraph.main.state import WorkflowPhase
from google_work_agent.adapters.langgraph.main.supervisor_control_adapter import (
    lifecycle_control_decision,
    lifecycle_state_update,
)
from google_work_agent.adapters.langgraph.main.supervisor_decision import SupervisorTarget


def test_lifecycle_control__projects_execution_disposition_without_legacy_target() -> None:
    result = {
        "__target__": "verification",
        "__logical_target__": "verification",
        "workflow_phase": "VERIFICATION",
        "execution_summary": {"routing_outcome": "EXECUTED"},
        "__workflow_control__": {"reason": "WRITE_EXECUTED"},
    }

    decision = lifecycle_control_decision(
        source_phase=WorkflowPhase.ACTION_EXECUTION,
        control_result=result,
    )
    update = lifecycle_state_update(result)

    assert decision["target"] == SupervisorTarget.VERIFICATION.value
    assert decision["reason_code"] == "WRITE_EXECUTED"
    assert "__target__" not in update
    assert "__logical_target__" not in update
    assert update["execution_summary"] == {"routing_outcome": "EXECUTED"}


def test_lifecycle_control__maps_reauth_suspend_to_explicit_boundary() -> None:
    decision = lifecycle_control_decision(
        source_phase=WorkflowPhase.PREFLIGHT,
        control_result={
            "__target__": "end",
            "__workflow_control__": {"reason": "REAUTH_REQUIRED"},
        },
    )

    assert decision["target"] == SupervisorTarget.REAUTH.value


def test_lifecycle_control__uses_changed_physical_target_over_stale_logical_state() -> None:
    state = {"__target__": "recovery", "__logical_target__": "recovery"}
    returned = {**state, "__target__": "end"}
    patch = {key: value for key, value in returned.items() if state.get(key) != value}

    decision = lifecycle_control_decision(
        source_phase=WorkflowPhase.RECOVERY,
        control_result=patch,
    )

    assert decision["target"] == SupervisorTarget.SUSPEND.value


def test_lifecycle_control__rejects_unregistered_main_target() -> None:
    with pytest.raises(ValueError, match="unregistered target"):
        lifecycle_control_decision(
            source_phase=WorkflowPhase.RECOVERY,
            control_result={"__target__": "invented_node"},
        )
