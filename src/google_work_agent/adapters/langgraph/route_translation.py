"""Profile-specific translation from supervisor targets to graph nodes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.application.workflows.supervisor import SupervisorTarget


@dataclass(frozen=True, slots=True)
class RouteTranslation:
    logical_target: str
    node: str


_COMMON_ROUTES = {
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
    SupervisorTarget.REAUTH.value: RouteTranslation("end", "end"),
    SupervisorTarget.RECOVERY.value: RouteTranslation("recovery", "recovery"),
    SupervisorTarget.FINALIZE.value: RouteTranslation("finalize", "finalize"),
}

_PROFILE_TOPOLOGIES = {
    GraphProfile.SINGLE_BASELINE: ("single_workflow",),
    GraphProfile.THREE_STAGE: ("stage_one", "stage_two", "stage_three"),
    GraphProfile.SIX_ROLE_BASELINE: (
        "request_understanding",
        "acquisition",
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
            target.value: RouteTranslation("acquisition", "acquisition")
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


@dataclass(frozen=True, slots=True)
class GraphRouteTranslator:
    profile: GraphProfile

    def topology(self) -> tuple[str, ...]:
        try:
            return _PROFILE_TOPOLOGIES[self.profile]
        except KeyError as error:
            raise ValueError(f"unsupported graph profile: {self.profile}") from error

    def translate(self, target: str) -> RouteTranslation:
        return _PROFILE_ROUTES.get(self.profile, {}).get(target, RouteTranslation("end", "end"))

    def confirmation_resume_target(self, interrupt_payload: Mapping[str, object]) -> str:
        origin_target = interrupt_payload.get("origin_target")
        if self.profile is GraphProfile.THREE_STAGE and isinstance(origin_target, str):
            if origin_target.startswith(("request_understanding.", "acquisition.")):
                return "stage_one"
            if origin_target.startswith(("context.", "analysis.", "planning.")):
                return "stage_two"
            if origin_target.startswith("review."):
                return "stage_three"
        if self.profile is GraphProfile.SINGLE_BASELINE:
            return "single_workflow"
        if self.profile is GraphProfile.SIX_ROLE_BASELINE:
            return "acquisition"
        return "source_planning"
