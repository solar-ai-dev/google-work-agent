"""Profile-specific translation from supervisor targets to graph nodes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.application.workflows.handoff_contracts import RegisteredResumeTargetRefV1
from google_work_agent.application.workflows.supervisor import SupervisorTarget
from google_work_agent.domain import RunStatus

RESUME_CONTRACT_VERSION = "resume-contract-v1"
RESPONSE_SYNTHESIS_TARGET = "RESPONSE_SYNTHESIS"


class UnroutableSupervisorTargetError(ValueError):
    """A Supervisor-decided target has no compiled-node mapping for this profile.

    Fail-closed: the caller must route this into Recovery
    (``CONTRACT_VIOLATION``), never silently reinterpret it as a normal
    "end" termination.
    """

    def __init__(self, *, target: str, profile: GraphProfile) -> None:
        self.target = target
        self.profile = profile
        super().__init__(
            f"unroutable supervisor target {target!r} for graph profile {profile.value!r}"
        )


@dataclass(frozen=True, slots=True)
class RouteTranslation:
    logical_target: str
    node: str


@dataclass(frozen=True, slots=True)
class ResumeTargetRegistry:
    """Immutable compiled-graph authority for confirmation resume targets."""

    graph_version: str
    _targets: Mapping[tuple[str, str], str]

    def issue(self, *, subgraph_id: str, node_id: str) -> RegisteredResumeTargetRefV1:
        if (subgraph_id, node_id) not in self._targets:
            raise ValueError("unregistered confirmation resume target")
        return {
            "subgraph_id": subgraph_id,  # type: ignore[typeddict-item]
            "node_id": node_id,
            "graph_version": self.graph_version,
        }

    def resolve(self, target: RegisteredResumeTargetRefV1) -> str:
        if target["graph_version"] != self.graph_version:
            raise ValueError("confirmation resume target graph version is invalid")
        node = self._targets.get((target["subgraph_id"], target["node_id"]))
        if node is None:
            raise ValueError("confirmation resume target is not registered")
        return node


_COMMON_ROUTES = {
    SupervisorTarget.TOOL_ROUTE.value: RouteTranslation("tool_route", "tool_route"),
    SupervisorTarget.DOMAIN_VALIDATION.value: RouteTranslation(
        "domain_validation", "domain_validation"
    ),
    SupervisorTarget.WAITING_CONFIRMATION.value: RouteTranslation(
        "waiting_confirmation", "waiting_confirmation"
    ),
    SupervisorTarget.WAITING_APPROVAL.value: RouteTranslation(
        "waiting_approval", "waiting_approval"
    ),
    SupervisorTarget.ACTION_EXECUTION.value: RouteTranslation(
        "action_execution", "action_execution"
    ),
    RESPONSE_SYNTHESIS_TARGET: RouteTranslation("response_synthesis", "response_synthesis"),
    SupervisorTarget.REAUTH.value: RouteTranslation("end", "end"),
    SupervisorTarget.RECOVERY.value: RouteTranslation("recovery", "recovery"),
    SupervisorTarget.FINALIZE.value: RouteTranslation("finalize", "finalize"),
}

_PROFILE_TOPOLOGIES = {
    GraphProfile.SINGLE_BASELINE: ("single_workflow",),
    GraphProfile.THREE_STAGE: ("stage_one", "stage_two", "stage_three"),
    GraphProfile.SIX_ROLE_BASELINE: (
        "request_understanding",
        "context_retriever",
        "work_analysis",
        "planning",
        "review",
    ),
}

_PROFILE_ROUTES = {
    GraphProfile.SINGLE_BASELINE: {
        **_COMMON_ROUTES,
        **{
            target.value: RouteTranslation("single_workflow", "single_workflow")
            for target in (
                SupervisorTarget.SOURCE_PLANNING,
                SupervisorTarget.API_ACQUISITION,
                SupervisorTarget.CONTEXT_RETRIEVAL,
                SupervisorTarget.WORK_ANALYSIS,
                SupervisorTarget.SOLUTION_PLANNING,
                SupervisorTarget.PLAN_REVIEW_INSPECT,
                SupervisorTarget.PLAN_REVIEW_RECHECK,
                SupervisorTarget.PLANNING_REVISE_ANSWER,
                SupervisorTarget.PLANNING_REVISE_PLAN,
            )
        },
    },
    GraphProfile.THREE_STAGE: {
        **_COMMON_ROUTES,
        SupervisorTarget.SOURCE_PLANNING.value: RouteTranslation("stage_one", "stage_one"),
        SupervisorTarget.API_ACQUISITION.value: RouteTranslation("stage_one", "stage_two"),
        **{
            target.value: RouteTranslation("stage_two", "stage_two")
            for target in (
                SupervisorTarget.CONTEXT_RETRIEVAL,
                SupervisorTarget.WORK_ANALYSIS,
                SupervisorTarget.SOLUTION_PLANNING,
                SupervisorTarget.PLANNING_REVISE_ANSWER,
                SupervisorTarget.PLANNING_REVISE_PLAN,
            )
        },
        **{
            target.value: RouteTranslation("stage_three", "stage_three")
            for target in (
                SupervisorTarget.PLAN_REVIEW_INSPECT,
                SupervisorTarget.PLAN_REVIEW_RECHECK,
            )
        },
    },
    GraphProfile.SIX_ROLE_BASELINE: {
        **_COMMON_ROUTES,
        **{
            target.value: RouteTranslation("context_retriever", "context_retriever")
            for target in (
                SupervisorTarget.SOURCE_PLANNING,
                SupervisorTarget.API_ACQUISITION,
            )
        },
        SupervisorTarget.CONTEXT_RETRIEVAL.value: RouteTranslation(
            "context_retriever", "context_retriever"
        ),
        SupervisorTarget.WORK_ANALYSIS.value: RouteTranslation("work_analysis", "work_analysis"),
        **{
            target.value: RouteTranslation("planning", "planning")
            for target in (
                SupervisorTarget.SOLUTION_PLANNING,
                SupervisorTarget.PLANNING_REVISE_ANSWER,
                SupervisorTarget.PLANNING_REVISE_PLAN,
            )
        },
        **{
            target.value: RouteTranslation("review", "review")
            for target in (
                SupervisorTarget.PLAN_REVIEW_INSPECT,
                SupervisorTarget.PLAN_REVIEW_RECHECK,
            )
        },
    },
}

_OWNER_BY_PREFIX = {
    "request_understanding.": "REQUEST_UNDERSTANDING",
    "tool_route.": "TOOL_ROUTE",
    "acquisition.": "RETRIEVAL",
    "context.": "RETRIEVAL",
    "retrieval.": "RETRIEVAL",
    "analysis.": "WORK_ANALYSIS",
    "work_analysis.": "WORK_ANALYSIS",
    "planning.": "PLANNING",
    "review.": "REVIEW",
}

_OWNER_DOMAIN_STATUS = {
    "REQUEST_UNDERSTANDING": RunStatus.ANALYZING,
    "TOOL_ROUTE": RunStatus.ANALYZING,
    "RETRIEVAL": RunStatus.RETRIEVING,
    "WORK_ANALYSIS": RunStatus.PLANNING,
    "PLANNING": RunStatus.PLANNING,
    "REVIEW": RunStatus.PLANNING,
}


def confirmation_owner(origin_target: str) -> str:
    for prefix, owner in _OWNER_BY_PREFIX.items():
        if origin_target.startswith(prefix):
            return owner
    raise ValueError(f"confirmation origin target has no registered owner: {origin_target}")


def confirmation_resume_status(owner_subgraph: str) -> RunStatus:
    try:
        return _OWNER_DOMAIN_STATUS[owner_subgraph]
    except KeyError as error:
        raise ValueError(f"unknown confirmation owner: {owner_subgraph}") from error


def build_resume_target_registry(profile: GraphProfile) -> ResumeTargetRegistry:
    """Build the fixed owner-to-compiled-node registry with the graph profile."""
    if profile is GraphProfile.SINGLE_BASELINE:
        targets = {
            ("REQUEST_UNDERSTANDING", "finalize"): "single_workflow",
            ("TOOL_ROUTE", "finalize"): "tool_route",
            ("RETRIEVAL", "finalize"): "single_workflow",
            ("WORK_ANALYSIS", "finalize"): "single_workflow",
            ("PLANNING", "finalize"): "single_workflow",
            ("REVIEW", "finalize"): "single_workflow",
        }
    elif profile is GraphProfile.THREE_STAGE:
        targets = {
            ("REQUEST_UNDERSTANDING", "finalize"): "stage_one",
            ("TOOL_ROUTE", "finalize"): "tool_route",
            ("RETRIEVAL", "finalize"): "stage_two",
            ("WORK_ANALYSIS", "finalize"): "stage_two",
            ("PLANNING", "finalize"): "stage_two",
            ("REVIEW", "finalize"): "stage_three",
        }
    else:
        targets = {
            ("REQUEST_UNDERSTANDING", "finalize"): "request_understanding",
            ("TOOL_ROUTE", "finalize"): "tool_route",
            ("RETRIEVAL", "finalize"): "context_retriever",
            ("WORK_ANALYSIS", "finalize"): "work_analysis",
            ("PLANNING", "finalize"): "planning",
            ("REVIEW", "finalize"): "review",
        }
    return ResumeTargetRegistry(
        graph_version=RESUME_CONTRACT_VERSION,
        _targets=targets,
    )


@dataclass(frozen=True, slots=True)
class GraphRouteTranslator:
    profile: GraphProfile

    def topology(self) -> tuple[str, ...]:
        try:
            return _PROFILE_TOPOLOGIES[self.profile]
        except KeyError as error:
            raise ValueError(f"unsupported graph profile: {self.profile}") from error

    def translate(self, target: str) -> RouteTranslation:
        routes = _PROFILE_ROUTES.get(self.profile)
        if routes is None:
            raise UnroutableSupervisorTargetError(target=target, profile=self.profile)
        translation = routes.get(target)
        if translation is None:
            raise UnroutableSupervisorTargetError(target=target, profile=self.profile)
        return translation

    def confirmation_resume_target(self, interrupt_payload: Mapping[str, object]) -> str:
        """Resolve confirmation resume through the compiled owner registry only."""
        origin_target = interrupt_payload.get("origin_target")
        if not isinstance(origin_target, str):
            raise ValueError("confirmation interrupt is missing origin_target")
        owner_subgraph = confirmation_owner(origin_target)
        registry = build_resume_target_registry(self.profile)
        resume_ref = registry.issue(subgraph_id=owner_subgraph, node_id="finalize")
        return registry.resolve(resume_ref)
