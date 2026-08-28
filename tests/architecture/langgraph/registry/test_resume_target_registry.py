from __future__ import annotations

from dataclasses import replace

import pytest

from google_work_agent.adapters.langgraph.registry.node_registry import NodeRegistry
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    MAIN_RESUME_STAGES,
    ResumeTargetRegistry,
)


def _registry() -> ResumeTargetRegistry:
    return ResumeTargetRegistry(
        node_registry=NodeRegistry(graph_version="graph-v1"),
        graph_version="graph-v1",
    )


def test_agent_resume_target_is_issued_from_node_and_profile_binding() -> None:
    registry = _registry()
    target = registry.issue_agent_node(
        "SIX_ROLE_BASELINE", "WORK_ANALYSIS", "analysis.finalize", "graph-v1"
    )

    assert target.kind == "AGENT_NODE"
    assert target.semantic_owner_id == "WORK_ANALYSIS"
    assert target.compiled_subgraph_id == "SIX_WORK_ANALYSIS"
    assert target.node_id == "analysis.finalize"
    assert target.graph_profile == "SIX_ROLE_BASELINE"
    registry.validate(target)


@pytest.mark.parametrize(
    "field,value",
    [
        ("graph_version", "graph-v0"),
        ("compiled_subgraph_id", "SIX_REVIEW"),
        ("node_id", "analysis.unknown"),
    ],
)
def test_agent_resume_target_validation_fails_closed(field: str, value: str) -> None:
    registry = _registry()
    target = registry.issue_agent_node(
        "SIX_ROLE_BASELINE", "WORK_ANALYSIS", "analysis.finalize", "graph-v1"
    )

    with pytest.raises(ValueError):
        registry.validate(replace(target, **{field: value}))  # type: ignore[arg-type]


def test_main_resume_stage_registry_is_closed_and_rejects_stale_version() -> None:
    assert {
        "RETRIEVAL_ENTRY",
        "PLANNING_ENTRY",
        "REVIEW_ENTRY",
        "PREFLIGHT",
        "READ_EXECUTION",
        "VERIFICATION",
        "RECOVERY",
        "CANCEL_RESOLUTION",
    } == MAIN_RESUME_STAGES
    registry = _registry()
    target = registry.issue_main_stage("SIX_ROLE_BASELINE", "RECOVERY", "graph-v1")
    registry.validate(target)
    with pytest.raises(ValueError):
        registry.validate(replace(target, graph_version="graph-v0"))
