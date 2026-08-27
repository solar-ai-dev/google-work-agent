from copy import deepcopy

import pytest

from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    bind_registry_candidates,
)
from google_work_agent.application.agents.tool_routing.contracts.semantic_route_candidate import (
    SemanticRouteCandidate,
)
from google_work_agent.application.agents.tool_routing.finalize_route import finalize_route
from google_work_agent.application.agents.tool_routing.validate_route import (
    ToolRouteValidationError,
    validate_route,
)
from google_work_agent.domain.action.model import EffectType
from google_work_agent.ports.connector.migration_contracts.tool_registry import (
    ConnectorToolCatalog,
    build_p0_tool_registry,
)


def _catalog() -> ConnectorToolCatalog:
    catalog = ConnectorToolCatalog()
    catalog.register(connector_id="google_workspace", registry=build_p0_tool_registry())
    return catalog


def test_validate_route__mismatched_output_tool__fails_closed() -> None:
    catalog = _catalog()
    ids = iter(f"id-{index}" for index in range(30))
    binding = bind_registry_candidates(
        candidate=SemanticRouteCandidate(
            ("TASK",), (("TASK", EffectType.CREATE),), "ACTION", "REQUIRED"
        ),
        tool_catalog=catalog,
        id_factory=lambda: next(ids),
    )
    intent = {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "goal",
        "completion_conditions": ["done"],
        "constraints": [],
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["TASK"],
        "analysis_requirement": "REQUIRED",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }
    selected_tools = {
        (item.resource_type, item.effect): item.eligible_tool_ids[0]
        for item in binding.output_candidates
    }
    result = finalize_route(
        request_intent=intent,
        binding=binding,
        selected_tools=selected_tools,
        tool_catalog=catalog,
        id_factory=lambda: next(ids),
    )
    plan = result["tool_route_plan"]
    assert plan is not None
    invalid = deepcopy(plan)
    assert invalid["output_plan"]["output_mode"] == "ACTION"
    invalid["output_plan"]["output_routes"][0]["selected_tool_id"] = "gmail_send"
    with pytest.raises(ToolRouteValidationError, match="binding is invalid"):
        validate_route(invalid, tool_catalog=catalog)
