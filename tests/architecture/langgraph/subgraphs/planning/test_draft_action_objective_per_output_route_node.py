import inspect

from google_work_agent.adapters.langgraph.subgraphs.planning.graph import PlanningSubgraph
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes import (
    draft_action_objective_per_output_route_node as node_module,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.projections import (
    draft_action_objective_per_output_route_projection as projection_module,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.routing import (
    route_after_draft_action_objective_per_output_route as routing_module,
)


def test_exact_objective_node_projection_router_are_wired() -> None:
    source = inspect.getsource(PlanningSubgraph.build)
    assert '"draft_action_objective_per_output_route"' in source
    assert callable(node_module.draft_action_objective_per_output_route_node)
    assert callable(projection_module.project_draft_action_objective_per_output_route_input)
    assert (
        routing_module.route_after_draft_action_objective_per_output_route(
            {"action_objective_candidates": [{}]}
        )
        == "compose_arguments_per_output_route"
    )
