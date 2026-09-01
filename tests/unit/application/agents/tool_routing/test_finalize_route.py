from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    bind_registry_candidates,
)
from google_work_agent.application.agents.tool_routing.contracts.semantic_route_candidate import (
    SemanticRouteCandidate,
)
from google_work_agent.application.agents.tool_routing.finalize_route import finalize_route
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.domain.action.model import EffectType


def _catalog() -> SignedToolRegistry:
    return load_signed_tool_registry()


def test_finalize_route__freezes_prebound_v2_plan_without_reowning_preconditions() -> None:
    catalog = _catalog()
    ids = iter(f"id-{index}" for index in range(30))
    binding = bind_registry_candidates(
        candidate=SemanticRouteCandidate(
            ("TASK", "TASK_LIST"),
            (("TASK", EffectType.CREATE),),
            "ACTION",
            "REQUIRED",
            (
                ("TASK", "POLICY_TASK_DUPLICATE_CHECK"),
                ("TASK_LIST", "POLICY_TASK_DUPLICATE_CHECK"),
            ),
        ),
        tool_catalog=catalog,
        id_factory=lambda: next(ids),
    )
    intent: RequestIntentV2 = {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "task create",
        "completion_conditions": ["created"],
        "constraints": [],
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["TASK"],
        "analysis_requirement": "REQUIRED",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }
    result = finalize_route(
        request_intent=intent,
        binding=binding,
        selected_tools={("TASK", "CREATE"): "tasks_create_task"},
        tool_catalog=catalog,
        id_factory=lambda: next(ids),
    )
    assert result["disposition"] == "ROUTE_READY"
    plan = result["tool_route_plan"]
    assert plan is not None and plan["schema_version"] == 2
    assert {route["resource_type"] for route in plan["input_plan"]["input_routes"]} == {
        "TASK",
        "TASK_LIST",
    }


def test_finalize_route__selection_outside_bound_set__blocks() -> None:
    catalog = _catalog()
    ids = iter(f"id-{index}" for index in range(30))
    binding = bind_registry_candidates(
        candidate=SemanticRouteCandidate((), (("TASK", EffectType.CREATE),), "ACTION", "NONE"),
        tool_catalog=catalog,
        id_factory=lambda: next(ids),
    )
    intent: RequestIntentV2 = {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "task create",
        "completion_conditions": ["created"],
        "constraints": [],
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["TASK"],
        "analysis_requirement": "NONE",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }
    result = finalize_route(
        request_intent=intent,
        binding=binding,
        selected_tools={("TASK", "CREATE"): "not_registry_eligible"},
        tool_catalog=catalog,
        id_factory=lambda: next(ids),
    )
    assert result["disposition"] == "BLOCKED"
    assert result["tool_route_plan"] is None
    assert any("outside the bound eligible set" in reason for reason in result["reason_codes"])
