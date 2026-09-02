from __future__ import annotations

from typing import cast

import pytest

from google_work_agent.adapters.langgraph.main.nodes.action_execution_node import (
    action_execution_node,
)
from google_work_agent.adapters.langgraph.main.nodes.cancel_resolution_node import (
    cancel_resolution_node,
)
from google_work_agent.adapters.langgraph.main.nodes.recovery_node import recovery_node
from google_work_agent.adapters.langgraph.main.nodes.verification_node import verification_node
from google_work_agent.adapters.langgraph.main.state import GraphState


def test_action_execution__projects_only__changed_control_fields() -> None:
    state = cast(
        GraphState,
        {"run_id": "run-1", "approved_plan_id": "plan-1", "__target__": "action"},
    )

    patch = action_execution_node(
        state,
        execute_claimed_action=lambda current: {
            **current,
            "__target__": "verification",
            "workflow_phase": "VERIFICATION",
        },
    )

    assert dict(patch) == {"__target__": "verification", "workflow_phase": "VERIFICATION"}


def test_verification_technical_failure__is_not_coerced__to_a_semantic_result() -> None:
    def fail(_state: object) -> dict[str, object]:
        raise TimeoutError("verification transport failed")

    with pytest.raises(TimeoutError, match="verification transport failed"):
        verification_node({"run_id": "run-1"}, verify_durable_effects=fail)


def test_recovery_projects__verification_without_invoking__a_write_seam() -> None:
    calls: list[str] = []

    def recover(state: GraphState) -> GraphState:
        calls.append("durable_recovery")
        return cast(
            GraphState,
            {**state, "__target__": "verification", "workflow_phase": "VERIFICATION"},
        )

    patch = recovery_node(
        cast(GraphState, {"run_id": "run-1", "__target__": "recovery"}),
        recover_from_durable_facts=recover,
    )

    assert calls == ["durable_recovery"]
    assert dict(patch) == {"__target__": "verification", "workflow_phase": "VERIFICATION"}


def test_cancel_resolution_requires__run_identity_and__runs_one_durable_step() -> None:
    calls: list[str] = []
    with pytest.raises(ValueError, match="run_id"):
        cancel_resolution_node({}, continue_cancel_resolution=lambda _run_id: {})

    def continue_cancel(run_id: str) -> dict[str, object]:
        calls.append(run_id)
        return {"__target__": "end", "execution_summary": {"result": "WAITING"}}

    patch = cancel_resolution_node(
        {"run_id": "run-1", "__target__": "cancel_resolution"},
        continue_cancel_resolution=continue_cancel,
    )

    assert calls == ["run-1"]
    assert patch == {"__target__": "end", "execution_summary": {"result": "WAITING"}}
