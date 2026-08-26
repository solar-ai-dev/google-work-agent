import pytest

from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    RESUME_CONTRACT_VERSION,
    GraphRouteTranslator,
    UnroutableSupervisorTargetError,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.registry.node_registry import (
    RUNTIME_NODE_OWNERS,
    NodeRegistry,
)
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    ResumeTargetRegistry,
)
from google_work_agent.application.orchestration.supervisor import SupervisorTarget


@pytest.mark.parametrize(
    ("profile", "topology"),
    [
        (GraphProfile.SINGLE_BASELINE, ("single_workflow",)),
        (GraphProfile.THREE_STAGE, ("stage_one", "stage_two", "stage_three")),
        (
            GraphProfile.SIX_ROLE_BASELINE,
            (
                "request_understanding",
                "context_retriever",
                "work_analysis",
                "planning",
                "review",
            ),
        ),
    ],
)
def test_profile_topology_is_preserved(
    profile: GraphProfile,
    topology: tuple[str, ...],
) -> None:
    assert GraphRouteTranslator(profile).topology() == topology


@pytest.mark.parametrize(
    ("profile", "target", "logical_target", "node"),
    [
        (
            GraphProfile.SINGLE_BASELINE,
            SupervisorTarget.PLAN_REVIEW_RECHECK,
            "single_workflow",
            "single_workflow",
        ),
        (
            GraphProfile.THREE_STAGE,
            SupervisorTarget.SOURCE_PLANNING,
            "stage_one",
            "stage_one",
        ),
        (
            GraphProfile.THREE_STAGE,
            SupervisorTarget.API_ACQUISITION,
            "stage_one",
            "stage_two",
        ),
        (
            GraphProfile.THREE_STAGE,
            SupervisorTarget.PLANNING_REVISE_PLAN,
            "stage_two",
            "stage_two",
        ),
        (
            GraphProfile.THREE_STAGE,
            SupervisorTarget.PLAN_REVIEW_RECHECK,
            "stage_three",
            "stage_three",
        ),
        (
            GraphProfile.SIX_ROLE_BASELINE,
            SupervisorTarget.API_ACQUISITION,
            "context_retriever",
            "context_retriever",
        ),
        (
            GraphProfile.SIX_ROLE_BASELINE,
            SupervisorTarget.CONTEXT_RETRIEVAL,
            "context_retriever",
            "context_retriever",
        ),
        (
            GraphProfile.SIX_ROLE_BASELINE,
            SupervisorTarget.PLANNING_REVISE_ANSWER,
            "planning",
            "planning",
        ),
        (
            GraphProfile.SIX_ROLE_BASELINE,
            SupervisorTarget.PLAN_REVIEW_INSPECT,
            "review",
            "review",
        ),
        (
            GraphProfile.SIX_ROLE_BASELINE,
            SupervisorTarget.RECOVERY,
            "recovery",
            "recovery",
        ),
    ],
)
def test_profile_route_translation_is_preserved(
    profile: GraphProfile,
    target: SupervisorTarget,
    logical_target: str,
    node: str,
) -> None:
    route = GraphRouteTranslator(profile).translate(target.value)

    assert route.logical_target == logical_target
    assert route.node == node


@pytest.mark.parametrize(
    "target",
    [
        # A SupervisorTarget enum member that is defined but has no entry
        # for this profile's route table (e.g. PREFLIGHT is never present
        # in any _PROFILE_ROUTES map -- runtime.py's domain_validation node
        # always rewrites it to ACTION_EXECUTION before this is reached in
        # production, but translate() itself must still fail closed rather
        # than silently defaulting to "end" if that override is ever
        # bypassed or a future target is added without a route entry).
        SupervisorTarget.PREFLIGHT.value,
        # A string that is not even a valid SupervisorTarget at all.
        "NOT_A_REAL_TARGET",
    ],
)
def test_translate_fails_closed_for_unmapped_target(target: str) -> None:
    with pytest.raises(UnroutableSupervisorTargetError):
        GraphRouteTranslator(GraphProfile.SIX_ROLE_BASELINE).translate(target)


def _resume_registry() -> ResumeTargetRegistry:
    return ResumeTargetRegistry(
        node_registry=NodeRegistry(graph_version=RESUME_CONTRACT_VERSION),
        graph_version=RESUME_CONTRACT_VERSION,
    )


def test_node_registry_contains_exact_canonical_runtime_nodes() -> None:
    assert len(RUNTIME_NODE_OWNERS) == 35


def test_resume_target_registry_issues_profile_bound_same_owner_target() -> None:
    registry = _resume_registry()
    target = registry.issue_agent_node(
        "SIX_ROLE_BASELINE",
        "RETRIEVAL",
        "retrieval.finalize",
        RESUME_CONTRACT_VERSION,
    )

    assert target.semantic_owner_id == "RETRIEVAL"
    assert target.compiled_subgraph_id == "SIX_RETRIEVAL"
    registry.validate(target)


@pytest.mark.parametrize(
    "target",
    [
        ("SIX_ROLE_BASELINE", "RETRIEVAL", "unknown", RESUME_CONTRACT_VERSION),
        ("SIX_ROLE_BASELINE", "RETRIEVAL", "retrieval.finalize", "wrong"),
        ("SIX_ROLE_BASELINE", "PLANNING", "retrieval.finalize", RESUME_CONTRACT_VERSION),
    ],
)
def test_resume_target_registry_rejects_unregistered_or_wrong_version(
    target: tuple[str, str, str, str],
) -> None:
    registry = _resume_registry()

    with pytest.raises(ValueError):
        registry.issue_agent_node(*target)  # type: ignore[arg-type]
