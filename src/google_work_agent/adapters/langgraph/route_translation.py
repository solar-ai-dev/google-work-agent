"""Profile-specific translation from supervisor targets to graph nodes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.application.workflows.handoff_contracts import (
    RegisteredResumeTargetRefV1,
)
from google_work_agent.application.workflows.supervisor import SupervisorTarget

RESUME_CONTRACT_VERSION = "resume-contract-v1"


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


def build_resume_target_registry(profile: GraphProfile) -> ResumeTargetRegistry:
    """Build the fixed registry together with the profile's compiled graph."""
    topology = _PROFILE_TOPOLOGIES[profile]
    if profile is GraphProfile.SINGLE_BASELINE:
        retrieval_node = "single_workflow"
    elif profile is GraphProfile.THREE_STAGE:
        retrieval_node = "stage_two"
    else:
        retrieval_node = "context_retriever"
    return ResumeTargetRegistry(
        graph_version=RESUME_CONTRACT_VERSION,
        _targets={
            ("RETRIEVAL", "finalize"): retrieval_node,
            ("REQUEST_UNDERSTANDING", "finalize"): topology[0],
            ("TOOL_ROUTE", "finalize"): topology[0],
            ("WORK_ANALYSIS", "finalize"): retrieval_node,
            ("PLANNING", "finalize"): retrieval_node,
            ("REVIEW", "finalize"): topology[-1],
        },
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
        return _PROFILE_ROUTES.get(self.profile, {}).get(target, RouteTranslation("end", "end"))

    def confirmation_resume_target(self, interrupt_payload: Mapping[str, object]) -> str:
        origin_target = interrupt_payload.get("origin_target")
        if origin_target == "tool_route.finalize":
            return self.topology()[0]
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
            # Pre-Prompt Runtime Closure: a confirmation whose ambiguity
            # originated in Request Understanding's own classify call must
            # re-enter classify (with the user's now-available answer) so
            # the ambiguity can actually be resolved into an updated
            # RequestIntentV2 -- resuming straight into "acquisition" (the
            # prior unconditional default) skipped classify entirely and
            # left request_understanding.classify's NEEDS_CONFIRMATION
            # branch permanently unreachable for this profile. Other
            # confirmation origins (acquisition.plan_sources,
            # context.assess_sufficiency, analysis.analyze, planning.*,
            # review.inspect) keep the existing "acquisition" resume target
            # unchanged -- that is a separate, out-of-scope gap.
            if isinstance(origin_target, str) and origin_target.startswith(
                "request_understanding."
            ):
                return "request_understanding"
            return "acquisition"
        return "source_planning"
