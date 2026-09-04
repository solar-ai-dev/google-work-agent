"""Deterministic Supervisor-target routing for the canonical Main graph."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.adapters.langgraph.main.supervisor_decision import SupervisorTarget
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile

RESUME_CONTRACT_VERSION = "resume-contract-v1"


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


_COMMON_ROUTES = {
    SupervisorTarget.DOMAIN_RECONCILE.value: RouteTranslation(
        "domain_reconcile", "domain_reconcile"
    ),
    SupervisorTarget.DOMAIN_VALIDATION.value: RouteTranslation(
        "domain_validation", "domain_validation"
    ),
    SupervisorTarget.PREFLIGHT.value: RouteTranslation("preflight", "preflight"),
    SupervisorTarget.WAITING_APPROVAL.value: RouteTranslation(
        "waiting_approval", "waiting_approval"
    ),
    SupervisorTarget.ACTION_EXECUTION.value: RouteTranslation(
        "action_execution", "action_execution"
    ),
    SupervisorTarget.VERIFICATION.value: RouteTranslation("verification", "verification"),
    SupervisorTarget.CANCEL_RESOLUTION.value: RouteTranslation(
        "cancel_resolution", "cancel_resolution"
    ),
    SupervisorTarget.RESPONSE_SYNTHESIS.value: RouteTranslation(
        "response_synthesis", "response_synthesis"
    ),
    SupervisorTarget.WAITING_CONFIRMATION.value: RouteTranslation("end", "end"),
    SupervisorTarget.SUSPEND.value: RouteTranslation("end", "end"),
    SupervisorTarget.REAUTH.value: RouteTranslation("end", "end"),
    SupervisorTarget.RECOVERY.value: RouteTranslation("recovery", "recovery"),
    SupervisorTarget.FINALIZE.value: RouteTranslation("response_synthesis", "response_synthesis"),
}


_PROFILE_TOPOLOGIES = {
    GraphProfile.SINGLE_BASELINE: ("single_workflow",),
    GraphProfile.THREE_STAGE: ("stage_one", "stage_two", "stage_three"),
    GraphProfile.SIX_ROLE_BASELINE: (
        "request_understanding",
        "tool_route",
        "context_retriever",
        "work_analysis",
        "planning",
        "review",
    ),
}

_PROFILE_ROUTES = {
    GraphProfile.SINGLE_BASELINE: {
        **_COMMON_ROUTES,
        SupervisorTarget.REQUEST_UNDERSTANDING.value: RouteTranslation(
            "request_understanding", "single_workflow"
        ),
        SupervisorTarget.TOOL_ROUTE.value: RouteTranslation("tool_route", "single_workflow"),
        SupervisorTarget.CONTEXT_RETRIEVAL.value: RouteTranslation(
            "retrieval_entry", "retrieval_entry"
        ),
        SupervisorTarget.WORK_ANALYSIS.value: RouteTranslation("work_analysis", "single_workflow"),
        SupervisorTarget.SOLUTION_PLANNING.value: RouteTranslation(
            "planning_entry", "planning_entry"
        ),
        SupervisorTarget.PLANNING_REVISE_ANSWER.value: RouteTranslation(
            "planning_entry", "planning_entry"
        ),
        SupervisorTarget.PLANNING_REVISE_PLAN.value: RouteTranslation(
            "planning_entry", "planning_entry"
        ),
        SupervisorTarget.PLAN_REVIEW_INSPECT.value: RouteTranslation(
            "review_entry", "review_entry"
        ),
        SupervisorTarget.PLAN_REVIEW_RECHECK.value: RouteTranslation(
            "review_entry", "review_entry"
        ),
    },
    GraphProfile.THREE_STAGE: {
        **_COMMON_ROUTES,
        SupervisorTarget.REQUEST_UNDERSTANDING.value: RouteTranslation(
            "request_understanding", "stage_one"
        ),
        SupervisorTarget.TOOL_ROUTE.value: RouteTranslation("tool_route", "stage_one"),
        SupervisorTarget.CONTEXT_RETRIEVAL.value: RouteTranslation(
            "retrieval_entry", "retrieval_entry"
        ),
        SupervisorTarget.WORK_ANALYSIS.value: RouteTranslation("work_analysis", "stage_two"),
        SupervisorTarget.SOLUTION_PLANNING.value: RouteTranslation(
            "planning_entry", "planning_entry"
        ),
        SupervisorTarget.PLANNING_REVISE_ANSWER.value: RouteTranslation(
            "planning_entry", "planning_entry"
        ),
        SupervisorTarget.PLANNING_REVISE_PLAN.value: RouteTranslation(
            "planning_entry", "planning_entry"
        ),
        SupervisorTarget.PLAN_REVIEW_INSPECT.value: RouteTranslation(
            "review_entry", "review_entry"
        ),
        SupervisorTarget.PLAN_REVIEW_RECHECK.value: RouteTranslation(
            "review_entry", "review_entry"
        ),
    },
    GraphProfile.SIX_ROLE_BASELINE: {
        **_COMMON_ROUTES,
        SupervisorTarget.REQUEST_UNDERSTANDING.value: RouteTranslation(
            "request_understanding", "request_understanding"
        ),
        SupervisorTarget.TOOL_ROUTE.value: RouteTranslation("tool_route", "tool_route"),
        SupervisorTarget.CONTEXT_RETRIEVAL.value: RouteTranslation(
            "retrieval_entry", "retrieval_entry"
        ),
        SupervisorTarget.WORK_ANALYSIS.value: RouteTranslation("work_analysis", "work_analysis"),
        **{
            target.value: RouteTranslation("planning_entry", "planning_entry")
            for target in (
                SupervisorTarget.SOLUTION_PLANNING,
                SupervisorTarget.PLANNING_REVISE_ANSWER,
                SupervisorTarget.PLANNING_REVISE_PLAN,
            )
        },
        **{
            target.value: RouteTranslation("review_entry", "review_entry")
            for target in (
                SupervisorTarget.PLAN_REVIEW_INSPECT,
                SupervisorTarget.PLAN_REVIEW_RECHECK,
            )
        },
    },
}


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
