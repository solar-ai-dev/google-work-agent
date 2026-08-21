from __future__ import annotations

from dataclasses import dataclass
from google_work_agent.application.agents.tool_routing.contracts.semantic_route_candidate import SemanticRouteCandidate
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import InputToolRouteV1, OutputToolRouteV1

@dataclass(frozen=True, slots=True)
class RouteBindingCandidateV1:
    semantic: SemanticRouteCandidate
    input_routes: tuple[InputToolRouteV1, ...]
    output_routes: tuple[OutputToolRouteV1, ...]
