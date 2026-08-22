from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.application.agents.tool_routing.contracts.semantic_route_candidate import SemanticRouteCandidate
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import InputToolRouteV1, ToolRouteEffect


@dataclass(frozen=True, slots=True)
class BoundOutputRouteCandidateV1:
    route_id: str
    resource_type: str
    connector_id: str
    effect: ToolRouteEffect
    eligible_tool_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RouteBindingCandidateV1:
    semantic: SemanticRouteCandidate
    input_routes: tuple[InputToolRouteV1, ...]
    output_candidates: tuple[BoundOutputRouteCandidateV1, ...]
