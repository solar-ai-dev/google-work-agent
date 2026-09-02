from __future__ import annotations

from dataclasses import replace

import pytest

from google_work_agent.adapters.langgraph.registry.checkpoint_target_resolver import (
    NativeCheckpointTargetResolver,
)
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


def test_agent_resume_target__is_issued_from__node_and_profile_binding() -> None:
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
def test_agent_resume__target_validation__fails_closed(field: str, value: str) -> None:
    registry = _registry()
    target = registry.issue_agent_node(
        "SIX_ROLE_BASELINE", "WORK_ANALYSIS", "analysis.finalize", "graph-v1"
    )

    with pytest.raises(ValueError):
        registry.validate(replace(target, **{field: value}))  # type: ignore[arg-type]


def test_main_resume_stage__registry_is_closed__and_rejects_stale_version() -> None:
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


@pytest.mark.parametrize(
    "unsafe_stage",
    [
        "INITIALIZE",
        "DOMAIN_VALIDATION",
        "ACTION_EXECUTION",
        "RESPONSE_SYNTHESIS",
        "TERMINAL_COMMIT",
        "FINALIZE",
    ],
)
def test_unsafe_main__stages_are__rejected(unsafe_stage: str) -> None:
    registry = _registry()

    with pytest.raises(ValueError, match="not registered"):
        registry.issue_main_stage(
            "SIX_ROLE_BASELINE",
            unsafe_stage,  # type: ignore[arg-type]
            "graph-v1",
        )


def test_main_resume__target_rejects_unknown__profile_without_fallback() -> None:
    registry = _registry()

    with pytest.raises(ValueError, match="profile"):
        registry.issue_main_stage("UNKNOWN", "RECOVERY", "graph-v1")  # type: ignore[arg-type]


def test_resume_registry__requires_the_node__registry_graph_version() -> None:
    with pytest.raises(ValueError, match="same graph version"):
        ResumeTargetRegistry(
            node_registry=NodeRegistry(graph_version="graph-v1"),
            graph_version="graph-v2",
        )


def test_resume_target__kind_cannot__be_forged() -> None:
    registry = _registry()
    target = registry.issue_agent_node(
        "SIX_ROLE_BASELINE", "PLANNING", "planning.assemble", "graph-v1"
    )

    with pytest.raises(ValueError, match="kind"):
        registry.validate(replace(target, kind="MAIN_CONTROL"))  # type: ignore[arg-type]


def test_every_profile_restarts__with_the_same__owner_subgraph_and_version() -> None:
    for profile in ("SINGLE_BASELINE", "THREE_STAGE", "SIX_ROLE_BASELINE"):
        before = ResumeTargetRegistry(NodeRegistry("graph-v1"), "graph-v1")
        target = before.issue_agent_node(
            profile,
            "PLANNING",
            "planning.assemble",
            "graph-v1",
        )

        restarted = ResumeTargetRegistry(NodeRegistry("graph-v1"), "graph-v1")
        restarted.validate(target)
        assert (
            restarted.issue_agent_node(
                profile,
                "PLANNING",
                "planning.assemble",
                "graph-v1",
            )
            == target
        )


def test_native_checkpoint__projection_uses_the__canonical_registry_binding() -> None:
    registry = _registry()
    fallback = registry.issue_main_stage("SIX_ROLE_BASELINE", "RECOVERY", "graph-v1")

    target = NativeCheckpointTargetResolver(registry)(
        {"channel_values": {"branch:to:context_retriever": True}},
        "SIX_ROLE_BASELINE",
        "graph-v1",
        fallback,
    )

    assert target == registry.issue_agent_node(
        "SIX_ROLE_BASELINE", "RETRIEVAL", "retrieval.plan_query", "graph-v1"
    )


def test_combined_profile__checkpoint_projection__preserves_profile_binding() -> None:
    registry = _registry()
    fallback = registry.issue_main_stage("THREE_STAGE", "RECOVERY", "graph-v1")

    target = NativeCheckpointTargetResolver(registry)(
        {
            "channel_values": {
                "branch:to:stage_two": True,
                "workflow_phase": "SOLUTION_PLANNING",
            }
        },
        "THREE_STAGE",
        "graph-v1",
        fallback,
    )

    assert target == registry.issue_agent_node(
        "THREE_STAGE", "PLANNING", "planning.outline_answer", "graph-v1"
    )


def test_checkpoint_fallback_must__match_the_current__profile_and_version() -> None:
    registry = _registry()
    fallback = registry.issue_main_stage("SINGLE_BASELINE", "RECOVERY", "graph-v1")

    with pytest.raises(ValueError, match="profile/version"):
        NativeCheckpointTargetResolver(registry)(
            {"channel_values": {}},
            "SIX_ROLE_BASELINE",
            "graph-v1",
            fallback,
        )
