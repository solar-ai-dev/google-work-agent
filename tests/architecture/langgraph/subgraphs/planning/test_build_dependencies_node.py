import inspect

from google_work_agent.adapters.langgraph.subgraphs.planning.graph import PlanningSubgraph
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.build_dependencies_node import (
    build_dependencies_node,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.projections import (
    build_dependencies_projection as projection_module,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.routing import (
    route_after_build_dependencies as routing_module,
)


def test_exact_dependency_node__projection_router_are__wired_without_prompt() -> None:
    source = inspect.getsource(PlanningSubgraph.build)
    assert 'graph.add_node("derive_dependencies"' in source
    assert callable(build_dependencies_node)
    assert callable(projection_module.project_build_dependencies_input)
    assert (
        routing_module.route_after_build_dependencies({"dependency_candidates": []}) == "assemble"
    )
    assert "Prompt" not in inspect.getsource(build_dependencies_node)
