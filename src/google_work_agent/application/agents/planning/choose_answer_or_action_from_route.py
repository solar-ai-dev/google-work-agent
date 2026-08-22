"""Choose Planning disposition from the already-frozen Tool Route."""

from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    PlanningDisposition,
)


def choose_answer_or_action_from_route(
    tool_route_plan: Mapping[str, object],
) -> PlanningDisposition:
    output_plan = tool_route_plan.get("output_plan")
    if not isinstance(output_plan, Mapping):
        raise ValueError("tool_route_plan.output_plan is required")
    output_mode = output_plan.get("output_mode")
    if output_mode == "ANSWER":
        return "ANSWER"
    if output_mode == "ACTION":
        return "ACTION"
    raise ValueError("unknown Tool Route output_mode")
