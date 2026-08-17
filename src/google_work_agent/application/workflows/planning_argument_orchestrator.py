"""Deterministic orchestration of per-output-route Planning argument calls.

This is intentionally narrower than final plan assembly.  Tool Route has
already frozen connector/resource/effect/tool identity.  The orchestrator
binds each route's selected business-argument schema, invokes the Argument
Writer exactly once for that route, validates the thin candidate, and returns
candidates in frozen route order.

Dependency synthesis, target-resource binding, user-visible reasons and final
ActionPlan assembly remain separate deterministic responsibilities; this
module does not guess them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.application.workflows.handoff_contracts import (
    EvidenceDraftV1,
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
    llm_result: StructuredLLMResult


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

    def compose(
        self,
        *,
        request: WorkflowStartRequest,
        request_intent: RequestIntentV2,
        output_routes: tuple[OutputToolRouteV1, ...],
        evidence_drafts: list[EvidenceDraftV1],
        analysis_result: WorkAnalysisResultV1 | None,
    ) -> tuple[RouteArgumentResult, ...]:
        if not output_routes:
            raise ValueError("ACTION planning requires at least one frozen output route")

        results: list[RouteArgumentResult] = []
        seen_route_ids: set[str] = set()
        for route in output_routes:
            route_id = route["route_id"]
            if route_id in seen_route_ids:
                raise ValueError(f"duplicate output route id: {route_id}")
            seen_route_ids.add(route_id)

            explicit_container_id = (
                self._explicit_container_provider(route)
                if self._explicit_container_provider is not None
                else None
            )
            bound_schema = self._default_container_resolver.bind_selected_tool_schema(
                route=route,
                selected_tool_schema=planning_tool_argument_schema(route["selected_tool_id"]),
                explicit_container_id=explicit_container_id,
            )
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


__all__ = ["PlanningArgumentOrchestrator", "RouteArgumentResult"]
