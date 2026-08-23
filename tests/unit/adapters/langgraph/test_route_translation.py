import pytest

from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    GraphRouteTranslator,
    UnroutableSupervisorTargetError,
    build_resume_target_registry,
    confirmation_owner,
    confirmation_resume_status,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.application.orchestration.supervisor import SupervisorTarget
from google_work_agent.domain import RunStatus


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


@pytest.mark.parametrize(
    ("profile", "origin_target", "expected"),
    [
        (GraphProfile.SINGLE_BASELINE, "review.inspect", "single_workflow"),
        (GraphProfile.THREE_STAGE, "request_understanding.classify", "stage_one"),
        (GraphProfile.THREE_STAGE, "analysis.analyze", "stage_two"),
        (GraphProfile.THREE_STAGE, "review.inspect", "stage_three"),
        (GraphProfile.SIX_ROLE_BASELINE, "request_understanding.classify", "request_understanding"),
        (GraphProfile.SIX_ROLE_BASELINE, "tool_route.finalize", "tool_route"),
        (GraphProfile.SIX_ROLE_BASELINE, "context.assess_sufficiency", "context_retriever"),
        (GraphProfile.SIX_ROLE_BASELINE, "analysis.analyze", "work_analysis"),
        (GraphProfile.SIX_ROLE_BASELINE, "planning.draft_plan", "planning"),
        (GraphProfile.SIX_ROLE_BASELINE, "review.inspect", "review"),
    ],
)
def test_confirmation_resume_target_returns_originating_owner(
    profile: GraphProfile,
    origin_target: str,
    expected: str,
) -> None:
    assert (
        GraphRouteTranslator(profile).confirmation_resume_target({"origin_target": origin_target})
        == expected
    )


def test_confirmation_resume_target_rejects_unknown_origin() -> None:
    with pytest.raises(ValueError, match="no registered owner"):
        GraphRouteTranslator(GraphProfile.SIX_ROLE_BASELINE).confirmation_resume_target(
            {"origin_target": "unknown"}
        )


@pytest.mark.parametrize(
    ("origin_target", "owner", "status"),
    [
        ("request_understanding.classify", "REQUEST_UNDERSTANDING", RunStatus.ANALYZING),
        ("tool_route.finalize", "TOOL_ROUTE", RunStatus.ANALYZING),
        ("retrieval.plan_query", "RETRIEVAL", RunStatus.RETRIEVING),
        ("context.assess_sufficiency", "RETRIEVAL", RunStatus.RETRIEVING),
        ("analysis.analyze", "WORK_ANALYSIS", RunStatus.PLANNING),
        ("planning.draft_plan", "PLANNING", RunStatus.PLANNING),
        ("review.inspect", "REVIEW", RunStatus.PLANNING),
    ],
)
def test_confirmation_owner_and_domain_resume_status_are_canonical(
    origin_target: str,
    owner: str,
    status: RunStatus,
) -> None:
    assert confirmation_owner(origin_target) == owner
    assert confirmation_resume_status(owner) is status


def test_resume_target_registry_issues_and_resolves_only_registered_target() -> None:
    registry = build_resume_target_registry(GraphProfile.SIX_ROLE_BASELINE)

    target = registry.issue(subgraph_id="RETRIEVAL", node_id="finalize")

    assert registry.resolve(target) == "context_retriever"


@pytest.mark.parametrize(
    "target",
    [
        {"subgraph_id": "RETRIEVAL", "node_id": "unknown", "graph_version": "resume-contract-v1"},
        {"subgraph_id": "RETRIEVAL", "node_id": "finalize", "graph_version": "wrong"},
        {"subgraph_id": "UNKNOWN", "node_id": "finalize", "graph_version": "resume-contract-v1"},
    ],
)
def test_resume_target_registry_rejects_unregistered_or_wrong_version(
    target: dict[str, str],
) -> None:
    registry = build_resume_target_registry(GraphProfile.SIX_ROLE_BASELINE)

    with pytest.raises(ValueError):
        registry.resolve(target)  # type: ignore[arg-type]
