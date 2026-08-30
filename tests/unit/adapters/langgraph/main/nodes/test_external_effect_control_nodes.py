from __future__ import annotations

import pytest

from google_work_agent.adapters.langgraph.main.nodes.action_execution_node import (
    action_execution_node,
)
from google_work_agent.adapters.langgraph.main.nodes.cancel_resolution_node import (
    cancel_resolution_node,
)
from google_work_agent.adapters.langgraph.main.nodes.recovery_node import recovery_node
from google_work_agent.adapters.langgraph.main.nodes.verification_node import verification_node


def test_action_execution_projects_only_changed_control_fields() -> None:
    state = {"run_id": "run-1", "approved_plan_id": "plan-1", "__target__": "action"}

    patch = action_execution_node(
        state,
        execute_claimed_action=lambda current: {
            **current,
            "__target__": "verification",
            "workflow_phase": "VERIFICATION",
        },
    )

    assert patch == {"__target__": "verification", "workflow_phase": "VERIFICATION"}


def test_verification_technical_failure_is_not_coerced_to_a_semantic_result() -> None:
    def fail(_state: object) -> dict[str, object]:
        raise TimeoutError("verification transport failed")

    with pytest.raises(TimeoutError, match="verification transport failed"):
        verification_node({"run_id": "run-1"}, verify_durable_effects=fail)


def test_recovery_projects_verification_without_invoking_a_write_seam() -> None:
    calls: list[str] = []

    patch = recovery_node(
        {"run_id": "run-1", "__target__": "recovery"},
        recover_from_durable_facts=lambda state: (
            calls.append("durable_recovery")
            or {**state, "__target__": "verification", "workflow_phase": "VERIFICATION"}
        ),
    )

    assert calls == ["durable_recovery"]
    assert patch == {"__target__": "verification", "workflow_phase": "VERIFICATION"}


def test_cancel_resolution_requires_run_identity_and_runs_one_durable_step() -> None:
    calls: list[str] = []
    with pytest.raises(ValueError, match="run_id"):
        cancel_resolution_node({}, continue_cancel_resolution=lambda _run_id: {})

    patch = cancel_resolution_node(
        {"run_id": "run-1", "__target__": "cancel_resolution"},
        continue_cancel_resolution=lambda run_id: (
            calls.append(run_id)
            or {"__target__": "end", "execution_summary": {"result": "WAITING"}}
        ),
    )

    assert calls == ["run-1"]
    assert patch == {"__target__": "end", "execution_summary": {"result": "WAITING"}}
