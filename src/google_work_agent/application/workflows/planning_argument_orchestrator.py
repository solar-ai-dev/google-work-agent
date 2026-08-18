"""Deterministic orchestration of per-output-route Planning argument calls.

Tool Route has already frozen connector/resource/effect/tool identity.  The
orchestrator binds each route's selected business-argument schema, invokes the
Argument Writer for that route, validates the thin candidate, and preserves
frozen route order.  Revision maps an already-assembled plan back to those
same route candidates only when route/tool/effect alignment is exact.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.application.workflows.handoff_contracts import (
    ActionPlanDraftV1,
    EvidenceDraftV1,
    ReviewIssueV1,
    RequestIntentV2,
    WorkAnalysisResultV1,
)
from google_work_agent.application.workflows.planning_argument_writer import (
    PlanningArgumentWriter,
)
from google_work_agent.application.workflows.planning_arguments import (
    BoundSelectedToolSchemaV1,
    DefaultContainerResolver,
    ToolArgumentCandidateV1,
    validate_tool_argument_candidate_v1,
)
from google_work_agent.application.workflows.planning_tool_schemas import (
    planning_tool_argument_schema,
)
from google_work_agent.application.workflows.tool_routing import OutputToolRouteV1
from google_work_agent.ports import StructuredLLMResult, WorkflowStartRequest


@dataclass(frozen=True, slots=True)
class RouteArgumentResult:
    route: OutputToolRouteV1
    bound_tool_schema: BoundSelectedToolSchemaV1
    candidate: ToolArgumentCandidateV1
    llm_result: StructuredLLMResult | None


class PlanningArgumentOrchestrator:
    """Run the canonical Argument Writer independently for each output route."""

    def __init__(
        self,
        *,
        writer: PlanningArgumentWriter,
        default_container_resolver: DefaultContainerResolver,
        explicit_container_provider: Callable[[OutputToolRouteV1], str | None] | None = None,
    ) -> None:
        self._writer = writer
        self._default_container_resolver = default_container_resolver
        self._explicit_container_provider = explicit_container_provider

    @property
    def prompt_ref(self):  # type: ignore[no-untyped-def]
        return self._writer.prompt_ref

    @property
    def revise_prompt_ref(self):  # type: ignore[no-untyped-def]
        return self._writer.revise_prompt_ref

    def compose(
        self,
        *,
        request: WorkflowStartRequest,
        request_intent: RequestIntentV2,
        output_routes: tuple[OutputToolRouteV1, ...],
        evidence_drafts: list[EvidenceDraftV1],
        analysis_result: WorkAnalysisResultV1 | None,
    ) -> tuple[RouteArgumentResult, ...]:
        self._validate_output_routes(output_routes)
        results: list[RouteArgumentResult] = []
        for route in output_routes:
            bound_schema = self._bound_schema(route)
            llm_result = self._writer.invoke(
                request=request,
                request_intent=request_intent,
                bound_tool_schema=bound_schema,
                evidence_drafts=evidence_drafts,
                analysis_result=analysis_result,
            )
            candidate = self._writer.validated_candidate(
                llm_result,
                bound_tool_schema=bound_schema,
                evidence_drafts=evidence_drafts,
            )
            results.append(
                RouteArgumentResult(
                    route=route,
                    bound_tool_schema=bound_schema,
                    candidate=candidate,
                    llm_result=llm_result,
                )
            )
        return tuple(results)

    def revise(
        self,
        *,
        request: WorkflowStartRequest,
        request_intent: RequestIntentV2,
        output_routes: tuple[OutputToolRouteV1, ...],
        evidence_drafts: list[EvidenceDraftV1],
        analysis_result: WorkAnalysisResultV1 | None,
        plan_draft: ActionPlanDraftV1,
        review_issues: list[ReviewIssueV1],
        review_summary: str | None,
    ) -> tuple[RouteArgumentResult, ...]:
        """Revise only affected per-route candidates under frozen route identity."""

        self._validate_output_routes(output_routes)
        write_actions = [action for action in plan_draft["actions"] if action["effect"] != "READ"]
        if len(write_actions) != len(output_routes):
            raise ValueError(
                "planning revision requires exactly one existing write action per frozen output route"
            )

        allowed_evidence_refs = {draft["evidence_id"] for draft in evidence_drafts}
        results: list[RouteArgumentResult] = []
        for route, action in zip(output_routes, write_actions, strict=True):
            if (
                action["tool_name"] != route["selected_tool_id"]
                or action["effect"] != route["effect"]
            ):
                raise ValueError(
                    f"existing plan action no longer aligns with frozen output route: {route['route_id']}"
                )
            bound_schema = self._bound_schema(route)
            candidate = validate_tool_argument_candidate_v1(
                {
                    "schema_version": 1,
                    "route_id": route["route_id"],
                    "arguments": dict(action["arguments"]),
                    "evidence_refs": list(action["evidence_refs"]),
                },
                bound_tool_schema=bound_schema,
                allowed_evidence_refs=allowed_evidence_refs,
            )
            relevant_issues = _issues_for_action(review_issues, action_id=action["action_id"])
            if not relevant_issues:
                results.append(
                    RouteArgumentResult(
                        route=route,
                        bound_tool_schema=bound_schema,
                        candidate=candidate,
                        llm_result=None,
                    )
                )
                continue

            llm_result = self._writer.revise(
                request=request,
                request_intent=request_intent,
                bound_tool_schema=bound_schema,
                evidence_drafts=evidence_drafts,
                analysis_result=analysis_result,
                candidate_output=candidate,
                review_issues=relevant_issues,
                review_summary=review_summary,
            )
            revised_candidate = self._writer.validated_candidate(
                llm_result,
                bound_tool_schema=bound_schema,
                evidence_drafts=evidence_drafts,
            )
            results.append(
                RouteArgumentResult(
                    route=route,
                    bound_tool_schema=bound_schema,
                    candidate=revised_candidate,
                    llm_result=llm_result,
                )
            )
        return tuple(results)

    def _bound_schema(self, route: OutputToolRouteV1) -> BoundSelectedToolSchemaV1:
        explicit_container_id = (
            self._explicit_container_provider(route)
            if self._explicit_container_provider is not None
            else None
        )
        return self._default_container_resolver.bind_selected_tool_schema(
            route=route,
            selected_tool_schema=planning_tool_argument_schema(route["selected_tool_id"]),
            explicit_container_id=explicit_container_id,
        )

    @staticmethod
    def _validate_output_routes(output_routes: tuple[OutputToolRouteV1, ...]) -> None:
        if not output_routes:
            raise ValueError("ACTION planning requires at least one frozen output route")
        route_ids = [route["route_id"] for route in output_routes]
        if len(route_ids) != len(set(route_ids)):
            raise ValueError("duplicate output route id")


def _issues_for_action(
    review_issues: list[ReviewIssueV1], *, action_id: str
) -> list[ReviewIssueV1]:
    result: list[ReviewIssueV1] = []
    for issue in review_issues:
        affected_action_ids = issue.get("affected_action_ids", [])
        if not affected_action_ids or action_id in affected_action_ids:
            result.append(issue)
    return result


__all__ = ["PlanningArgumentOrchestrator", "RouteArgumentResult"]
