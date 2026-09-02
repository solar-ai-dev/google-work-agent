import inspect
from typing import cast

from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.execute_read_node import (
    execute_read_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.nodes.plan_query_node import (
    plan_query_node,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections import (
    select_evidence_projection,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.nodes import (
    validate_relations_node,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.projections import (
    validate_relations_projection,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import (
    WorkAnalysisLocalState,
)


def test_owned_nodes_do__not_execute_mcp__or_provider_directly() -> None:
    source = "\n".join(
        inspect.getsource(node)
        for node in (
            execute_read_node,
            plan_query_node,
            validate_relations_node.validate_relations_node,
        )
    ).lower()
    assert "mcp" not in source
    assert "googleapiclient" not in source
    assert "provider" not in source
    assert "sqlite" not in source


def test_retrieval_projection__is_operation__allowlisted() -> None:
    state = {
        "request_intent": {"goal": "find evidence"},
        "rag_candidates": [],
        "exclusion_obligation_segment_ids": ["segment-1"],
        "foreign": {"secret": True},
    }
    assert dict(select_evidence_projection.project_select_evidence_input(state)) == {
        "request_intent": {"goal": "find evidence"},
        "rag_candidates": [],
        "exclusion_obligation_segment_ids": ["segment-1"],
    }


def test_work_analysis__projection_is__operation_allowlisted() -> None:
    state = cast(
        WorkAnalysisLocalState,
        {
            "fact_candidates": [],
            "entity_relation_candidates": [],
            "temporal_dependency_candidates": [],
            "duplicate_conflict_candidates": [],
            "current_source_relations": [],
            "evidence_refs": [],
            "planning": {"x": 1},
        },
    )
    assert validate_relations_projection.project_validate_relations_input(state) == {
        "work_facts": [],
        "entity_relation_candidates": [],
        "temporal_dependency_candidates": [],
        "duplicate_conflict_candidates": [],
        "current_source_relations": [],
        "allowed_evidence_refs": set(),
    }
