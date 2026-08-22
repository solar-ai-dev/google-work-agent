"""Canonical Work Analysis LangGraph subgraph."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.subgraphs.work_analysis.nodes.assemble_work_analysis_node import assemble_work_analysis_node
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.nodes.assess_information_gaps_node import assess_information_gaps_node
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.nodes.assess_operational_risks_node import assess_operational_risks_node
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.nodes.detect_duplicate_conflict_candidates_node import detect_duplicate_conflict_candidates_node
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.nodes.extract_work_facts_node import extract_work_facts_node
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.nodes.resolve_entity_relations_node import resolve_entity_relations_node
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.nodes.resolve_temporal_dependencies_node import resolve_temporal_dependencies_node
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.nodes.validate_relations_node import validate_relations_node
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.nodes.validate_work_analysis_node import validate_work_analysis_node
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.routing.route_after_assess_information_gaps import route_after_assess_information_gaps
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import WorkAnalysisState


def build_work_analysis_graph():
    graph = StateGraph(WorkAnalysisState)
    graph.add_node("extract_work_facts", extract_work_facts_node)
    graph.add_node("resolve_entity_relations", resolve_entity_relations_node)
    graph.add_node("resolve_temporal_dependencies", resolve_temporal_dependencies_node)
    graph.add_node("detect_duplicate_conflict_candidates", detect_duplicate_conflict_candidates_node)
    graph.add_node("validate_relations", validate_relations_node)
    graph.add_node("assess_information_gaps", assess_information_gaps_node)
    graph.add_node("assess_operational_risks", assess_operational_risks_node)
    graph.add_node("assemble_work_analysis", assemble_work_analysis_node)
    graph.add_node("validate_work_analysis", validate_work_analysis_node)
    graph.add_edge(START, "extract_work_facts")
    graph.add_edge("extract_work_facts", "resolve_entity_relations")
    graph.add_edge("resolve_entity_relations", "resolve_temporal_dependencies")
    graph.add_edge("resolve_temporal_dependencies", "detect_duplicate_conflict_candidates")
    graph.add_edge("detect_duplicate_conflict_candidates", "validate_relations")
    graph.add_edge("validate_relations", "assess_information_gaps")
    graph.add_conditional_edges("assess_information_gaps", route_after_assess_information_gaps, {"end": END, "assess_operational_risks": "assess_operational_risks"})
    graph.add_edge("assess_operational_risks", "assemble_work_analysis")
    graph.add_edge("assemble_work_analysis", "validate_work_analysis")
    graph.add_edge("validate_work_analysis", END)
    return graph.compile()
