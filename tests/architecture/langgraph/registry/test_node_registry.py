from __future__ import annotations

from google_work_agent.adapters.langgraph.registry.node_registry import (
    PROFILE_OWNER_BINDINGS,
    RUNTIME_NODE_OWNERS,
    NodeRegistry,
)


def test_node_registry_is_the_exact_canonical_35_node_manifest() -> None:
    assert RUNTIME_NODE_OWNERS == {
        "request.identify_goal": "REQUEST_UNDERSTANDING",
        "request.detect_ambiguity": "REQUEST_UNDERSTANDING",
        "request.finalize": "REQUEST_UNDERSTANDING",
        "route.determine_resources": "TOOL_ROUTE",
        "route.bind_candidates": "TOOL_ROUTE",
        "route.select_tool": "TOOL_ROUTE",
        "route.finalize": "TOOL_ROUTE",
        "route.validate": "TOOL_ROUTE",
        "retrieval.plan_query": "RETRIEVAL",
        "retrieval.build_query": "RETRIEVAL",
        "retrieval.execute_read": "RETRIEVAL",
        "retrieval.normalize_segments": "RETRIEVAL",
        "retrieval.rag_retrieve": "RETRIEVAL",
        "retrieval.select_evidence": "RETRIEVAL",
        "retrieval.assess_sufficiency": "RETRIEVAL",
        "retrieval.finalize": "RETRIEVAL",
        "analysis.extract_facts": "WORK_ANALYSIS",
        "analysis.resolve_entity_relations": "WORK_ANALYSIS",
        "analysis.resolve_temporal_dependencies": "WORK_ANALYSIS",
        "analysis.detect_duplicate_conflict_candidates": "WORK_ANALYSIS",
        "analysis.validate_relations": "WORK_ANALYSIS",
        "analysis.assess_information_gaps": "WORK_ANALYSIS",
        "analysis.assess_operational_risks": "WORK_ANALYSIS",
        "analysis.finalize": "WORK_ANALYSIS",
        "planning.outline_answer": "PLANNING",
        "planning.compose_answer": "PLANNING",
        "planning.draft_action_objective_per_output_route": "PLANNING",
        "planning.compose_arguments_per_output_route": "PLANNING",
        "planning.derive_dependencies": "PLANNING",
        "planning.assemble": "PLANNING",
        "review.inspect_goal_and_evidence": "REVIEW",
        "review.inspect_action_scope_route": "REVIEW",
        "review.inspect_constraints_policy": "REVIEW",
        "review.aggregate_findings": "REVIEW",
        "review.recheck": "REVIEW",
    }


def test_profile_owner_bindings_are_closed_and_exact() -> None:
    assert PROFILE_OWNER_BINDINGS == {
        "SINGLE_BASELINE": {
            "REQUEST_UNDERSTANDING": "UNIFIED_AGENT",
            "TOOL_ROUTE": "UNIFIED_AGENT",
            "RETRIEVAL": "UNIFIED_AGENT",
            "WORK_ANALYSIS": "UNIFIED_AGENT",
            "PLANNING": "UNIFIED_AGENT",
            "REVIEW": "UNIFIED_AGENT",
        },
        "THREE_STAGE": {
            "REQUEST_UNDERSTANDING": "STAGE_REQUEST_ROUTE_RETRIEVAL",
            "TOOL_ROUTE": "STAGE_REQUEST_ROUTE_RETRIEVAL",
            "RETRIEVAL": "STAGE_REQUEST_ROUTE_RETRIEVAL",
            "WORK_ANALYSIS": "STAGE_ANALYSIS_PLANNING",
            "PLANNING": "STAGE_ANALYSIS_PLANNING",
            "REVIEW": "STAGE_REVIEW",
        },
        "SIX_ROLE_BASELINE": {
            "REQUEST_UNDERSTANDING": "SIX_REQUEST_UNDERSTANDING",
            "TOOL_ROUTE": "SIX_TOOL_ROUTE",
            "RETRIEVAL": "SIX_RETRIEVAL",
            "WORK_ANALYSIS": "SIX_WORK_ANALYSIS",
            "PLANNING": "SIX_PLANNING",
            "REVIEW": "SIX_REVIEW",
        },
    }


def test_node_registry_rejects_stale_unknown_and_wrong_owner_bindings() -> None:
    registry = NodeRegistry(graph_version="graph-v1")
    assert registry.contains("graph-v1", "SIX_ROLE_BASELINE", "PLANNING", "planning.assemble")
    assert not registry.contains("graph-v0", "SIX_ROLE_BASELINE", "PLANNING", "planning.assemble")
    assert not registry.contains("graph-v1", "SIX_ROLE_BASELINE", "REVIEW", "planning.assemble")
    assert not registry.contains("graph-v1", "SIX_ROLE_BASELINE", "PLANNING", "planning.unknown")
