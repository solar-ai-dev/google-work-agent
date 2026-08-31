import re
from pathlib import Path

from google_work_agent.adapters.langgraph.subgraphs.work_analysis.routing import (
    route_after_assemble_work_analysis,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import (
    WorkAnalysisStateV2,
)


def test_finalize_is_one_prompt_free_assemble_validate_node() -> None:
    owner = Path(__file__).resolve().parents[5] / (
        "src/google_work_agent/adapters/langgraph/subgraphs/work_analysis"
    )
    node = (owner / "nodes/assemble_work_analysis_node.py").read_text(encoding="utf-8")
    assert "project_assemble_work_analysis_input" in node
    assert "assemble_work_analysis(" in node
    assert "validate_work_analysis(" in node
    assert "PromptReference" not in node
    assert not (owner / "nodes/validate_work_analysis_node.py").exists()
    assert not (owner / "routing/route_after_validate_work_analysis.py").exists()


def test_finalize_uses_the_canonical_closed_router() -> None:
    owner = Path(__file__).resolve().parents[5] / (
        "src/google_work_agent/adapters/langgraph/subgraphs/work_analysis"
    )
    graph = (owner / "graph.py").read_text(encoding="utf-8")

    assert "route_after_assemble_work_analysis" in graph
    assert "_route_after_finalize" not in graph
    assert (
        route_after_assemble_work_analysis.route_after_assemble_work_analysis(
            {"final_analysis": {}}
        )
        == "end"
    )
    assert (
        route_after_assemble_work_analysis.route_after_assemble_work_analysis(
            {"__work_analysis_retry_confirmation__": True}
        )
        == "assess_operational_risks"
    )


def test_work_analysis_graph_and_state_are_exact() -> None:
    owner = Path(__file__).resolve().parents[5] / (
        "src/google_work_agent/adapters/langgraph/subgraphs/work_analysis"
    )
    graph = (owner / "graph.py").read_text(encoding="utf-8")
    nodes = set(re.findall(r'graph\.add_node\(\s*"([^"]+)"', graph))
    assert nodes == {
        "extract_work_facts",
        "resolve_entity_relations",
        "resolve_temporal_dependencies",
        "detect_duplicate_conflict_candidates",
        "validate_relations",
        "assess_information_gaps",
        "assess_operational_risks",
        "finalize",
    }

    assert set(WorkAnalysisStateV2.__annotations__) == {
        "user_request",
        "request_intent",
        "evidence_refs",
        "fact_candidates",
        "entity_relation_candidates",
        "temporal_dependency_candidates",
        "duplicate_conflict_candidates",
        "validated_relations",
        "relation_validation_ambiguities",
        "ambiguity_candidates",
        "retrieval_needs",
        "operational_risk_candidates",
        "final_analysis",
    }
