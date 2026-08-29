import inspect

from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.execute_read_node import (
    execute_read_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.plan_query_node import (
    plan_query_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections.retrieval_operation_projection import (
    project_retrieval_operation_input,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.nodes.validate_relations_node import (
    validate_relations_node,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.projections.work_analysis_operation_projection import (
    project_work_analysis_operation_input,
)


def test_owned_nodes_do_not_execute_mcp_or_provider_directly():
    source = "\n".join(
        inspect.getsource(node)
        for node in (execute_read_node, plan_query_node, validate_relations_node)
    ).lower()
    assert "mcp" not in source
    assert "googleapiclient" not in source
    assert "provider" not in source
    assert "sqlite" not in source


def test_retrieval_projection_is_operation_allowlisted():
    state = {
        "operation_inputs": {
            "select_evidence": {"candidates": "c"},
            "foreign": {"secret": True},
        }
    }
    assert project_retrieval_operation_input(state, "select_evidence") == {"candidates": "c"}
    try:
        project_retrieval_operation_input(state, "foreign")
    except ValueError:
        pass
    else:
        raise AssertionError("foreign retrieval operation must not project")


def test_work_analysis_projection_is_operation_allowlisted():
    state = {
        "operation_inputs": {
            "validate_relations": {"relation_candidates": []},
            "planning": {"x": 1},
        }
    }
    assert project_work_analysis_operation_input(state, "validate_relations") == {
        "relation_candidates": []
    }
    try:
        project_work_analysis_operation_input(state, "planning")
    except ValueError:
        pass
    else:
        raise AssertionError("foreign owner input must not project")
