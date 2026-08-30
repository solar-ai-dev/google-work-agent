"""Closed registry for the canonical 35 Agent runtime nodes."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from google_work_agent.adapters.langgraph.profiles.profile_registry import (
    get_profile_owner_bindings,
    supported_graph_profiles,
)
from google_work_agent.ports.system.contracts.workflow_binding import GraphProfileIdV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    CompiledAgentSubgraphIdV1,
    SemanticAgentOwnerIdV1,
)

RUNTIME_NODE_OWNERS: dict[str, SemanticAgentOwnerIdV1] = {
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

PROFILE_OWNER_BINDINGS = MappingProxyType(
    {
        profile.value: get_profile_owner_bindings(profile)
        for profile in supported_graph_profiles()
    }
)


@dataclass(frozen=True, slots=True)
class NodeRegistry:
    graph_version: str

    def get_required(
        self,
        graph_version: str,
        graph_profile: GraphProfileIdV1,
        semantic_owner_id: SemanticAgentOwnerIdV1,
        node_id: str,
    ) -> CompiledAgentSubgraphIdV1:
        if graph_version != self.graph_version:
            raise ValueError("runtime node graph version is stale or unknown")
        if RUNTIME_NODE_OWNERS.get(node_id) != semantic_owner_id:
            raise ValueError("runtime node is not registered to the semantic owner")
        try:
            return PROFILE_OWNER_BINDINGS[graph_profile][semantic_owner_id]
        except KeyError as error:
            raise ValueError("runtime node profile/owner binding is unknown") from error

    def contains(
        self,
        graph_version: str,
        graph_profile: GraphProfileIdV1,
        semantic_owner_id: SemanticAgentOwnerIdV1,
        node_id: str,
    ) -> bool:
        try:
            self.get_required(graph_version, graph_profile, semantic_owner_id, node_id)
        except ValueError:
            return False
        return True


__all__ = ["NodeRegistry", "PROFILE_OWNER_BINDINGS", "RUNTIME_NODE_OWNERS"]
