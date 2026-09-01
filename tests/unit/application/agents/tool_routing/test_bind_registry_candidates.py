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


def test_task_create_binds_bounded_registry_candidates_and_read_dependency() -> None:
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
