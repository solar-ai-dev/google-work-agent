# ruff: noqa: E501

import inspect

from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.execute_read_node import (
    execute_read_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.plan_query_node import (
    plan_query_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections.select_evidence_projection import (
    project_select_evidence_input,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.nodes.validate_relations_node import (
    validate_relations_node,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.projections.validate_relations_projection import (
    project_validate_relations_input,
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
        "request_intent": {"goal": "find evidence"},
        "rag_candidates": [],
        "exclusion_obligation_segment_ids": ["segment-1"],
        "foreign": {"secret": True},
    }
    assert project_select_evidence_input(state) == {
        "request_intent": {"goal": "find evidence"},
        "rag_candidates": [],
        "exclusion_obligation_segment_ids": ["segment-1"],
    }


def test_work_analysis_projection_is_operation_allowlisted():
    state = {
        "fact_candidates": [],
        "entity_relation_candidates": [],
        "temporal_dependency_candidates": [],
        "duplicate_conflict_candidates": [],
        "current_source_relations": [],
        "evidence_refs": [],
        "planning": {"x": 1},
    }
    assert project_validate_relations_input(state) == {
        "work_facts": [],
        "entity_relation_candidates": [],
        "temporal_dependency_candidates": [],
        "duplicate_conflict_candidates": [],
        "current_source_relations": [],
        "allowed_evidence_refs": set(),
    }
