from __future__ import annotations

from dataclasses import fields
from typing import get_args

from google_work_agent.ports.system.contracts.workflow_binding import (
    GraphProfileIdV1,
    WorkflowBindingV1,
)


def test_workflow_binding_has_exact_canonical_shape() -> None:
    assert get_args(GraphProfileIdV1.__value__) == (
        "SINGLE_BASELINE",
        "THREE_STAGE",
        "SIX_ROLE_BASELINE",
    )
    assert tuple(field.name for field in fields(WorkflowBindingV1)) == (
        "schema_version",
        "workflow_key",
        "run_id",
        "langgraph_thread_id",
        "graph_profile",
        "graph_version",
        "requested_mode",
        "created_at_ms",
    )
