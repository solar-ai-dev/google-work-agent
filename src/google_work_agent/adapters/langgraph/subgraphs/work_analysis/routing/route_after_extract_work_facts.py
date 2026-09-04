from collections.abc import Mapping
from typing import cast

from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)
from google_work_agent.application.agents.tool_routing.resolve_policy_preconditions import (
    policy_analysis_required,
)


def route_after_extract_work_facts(state: object) -> str:
    """Do not spend three Provider calls on relations with no possible operands."""

    if isinstance(state, Mapping):
        plan = state.get("tool_route_plan")
        policy_required = isinstance(plan, Mapping) and policy_analysis_required(
            cast(ToolRoutePlanV2, plan)
        )
        intent = state.get("request_intent")
        explicit_analysis = isinstance(intent, Mapping) and (
            intent.get("analysis_requirement") == "REQUIRED"
        )
        if policy_required and not explicit_analysis:
            return "detect_duplicate_conflict_candidates"
        facts = state.get("fact_candidates")
        if isinstance(facts, list) and len(facts) < 2:
            if policy_required:
                return "detect_duplicate_conflict_candidates"
            return "validate_relations"
    return "resolve_entity_relations"
