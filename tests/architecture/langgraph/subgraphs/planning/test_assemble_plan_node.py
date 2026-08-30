import inspect

from google_work_agent.adapters.langgraph.subgraphs.planning.graph import PlanningSubgraph
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.assemble_plan_node import (
    assemble_plan_node,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.projections import (
    assemble_plan_projection as projection_module,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.routing import (
    route_after_assemble_plan as routing_module,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.state import PlanningStateV2


def test_assemble_is_one_runtime_node_for_assembly_and_validation() -> None:
    source = inspect.getsource(PlanningSubgraph.build)
    assert 'graph.add_node("assemble"' in source
    node_source = inspect.getsource(assemble_plan_node)
    assert "assemble_plan(" in node_source
    assert "validate_plan(" in node_source
    assert callable(projection_module.project_assemble_plan_input)
    assert routing_module.route_after_assemble_plan({"final_result": {}}) == "end"
    assert PlanningStateV2.__annotations__.keys() == {
        "user_request",
        "request_intent",
        "output_plan",
        "work_analysis",
        "evidence_refs",
        "action_objective_candidates",
        "argument_candidates",
        "dependency_candidates",
        "final_result",
    }
