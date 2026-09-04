from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    bind_registry_candidates,
)
from google_work_agent.application.agents.tool_routing.contracts.semantic_route_candidate import (
    SemanticRouteCandidate,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.domain.action.model import EffectType


def _catalog() -> SignedToolRegistry:
    return load_signed_tool_registry()


def test_task_create_binds__bounded_registry_candidates__and_read_dependency() -> None:
    ids = iter(f"route-{index}" for index in range(10))
    binding = bind_registry_candidates(
        candidate=SemanticRouteCandidate(
            input_resource_types=("TASK",),
            output_pairs=(("TASK", EffectType.CREATE),),
            output_mode="ACTION",
            analysis_requirement="REQUIRED",
        ),
        tool_catalog=_catalog(),
        id_factory=lambda: next(ids),
    )
    bound = binding.output_candidates[0]
    assert bound.resource_type == "TASK"
    assert bound.effect == "CREATE"
    assert bound.connector_id == "google_workspace"
    assert bound.eligible_tool_ids == ("tasks_create_task",)
    assert {route["resource_type"] for route in binding.input_routes} == {"TASK", "TASK_LIST"}


def test_selected_gmail_thread__binds_exact_read__without_discovery_dependency() -> None:
    ids = iter(f"route-{index}" for index in range(10))
    binding = bind_registry_candidates(
        candidate=SemanticRouteCandidate(
            input_resource_types=("GMAIL_THREAD",),
            output_pairs=(),
            output_mode="ANSWER",
            analysis_requirement="REQUIRED",
            input_reason_codes=(("GMAIL_THREAD", "RESOURCE_SELECTED"),),
        ),
        tool_catalog=_catalog(),
        id_factory=lambda: next(ids),
    )

    assert len(binding.input_routes) == 1
    route = binding.input_routes[0]
    assert route["resource_type"] == "GMAIL_THREAD"
    assert route["reason_codes"] == ["RESOURCE_SELECTED"]
    assert "gmail_get_thread" in route["allowed_read_tool_ids"]


def test_general_gmail_thread__avoids_redundant__message_detail_route() -> None:
    ids = iter(f"route-{index}" for index in range(10))
    binding = bind_registry_candidates(
        candidate=SemanticRouteCandidate(
            input_resource_types=("GMAIL_THREAD",),
            output_pairs=(),
            output_mode="ANSWER",
            analysis_requirement="NONE",
        ),
        tool_catalog=_catalog(),
        id_factory=lambda: next(ids),
    )

    assert [route["resource_type"] for route in binding.input_routes] == ["GMAIL_THREAD"]
