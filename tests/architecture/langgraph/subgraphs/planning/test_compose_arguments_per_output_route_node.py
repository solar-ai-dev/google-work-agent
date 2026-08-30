import inspect

from google_work_agent.adapters.langgraph.subgraphs.planning.graph import PlanningSubgraph
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes import (
    compose_arguments_per_output_route_node as node_module,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.projections import (
    compose_arguments_per_output_route_projection as projection_module,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.routing import (
    route_after_compose_arguments_per_output_route as routing_module,
)


def test_exact_arguments_node_projection_router_are_wired() -> None:
    source = inspect.getsource(PlanningSubgraph.build)
    assert '"compose_arguments_per_output_route"' in source
    assert callable(node_module.compose_arguments_per_output_route_node)
    assert callable(projection_module.project_compose_arguments_per_output_route_input)
    assert (
        routing_module.route_after_compose_arguments_per_output_route({"argument_candidates": [{}]})
        == "derive_dependencies"
    )
