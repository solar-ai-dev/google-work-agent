"""Closed Evaluation target ID to exact Product symbol registry."""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from evaluation.contracts.experiment_config import ExperimentTargetV1


class TargetResolutionError(ValueError):
    """Raised when a target is not in the closed current registry."""


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    target_kind: Literal["NODE", "SUBGRAPH", "MAIN_PROFILE"]
    target_id: str
    module: str
    symbol: str

    def load(self) -> Any:
        module = importlib.import_module(self.module)
        try:
            return getattr(module, self.symbol)
        except AttributeError as error:
            raise TargetResolutionError(
                f"registered Product symbol is absent: {self.module}:{self.symbol}"
            ) from error


_NODE_MODULE_ROOT = "google_work_agent.adapters.langgraph.subgraphs"
NODE_TARGETS: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "request.identify_goal": (
            f"{_NODE_MODULE_ROOT}.request_understanding.nodes.identify_goal_node",
            "identify_goal_node",
        ),
        "request.detect_ambiguity": (
            f"{_NODE_MODULE_ROOT}.request_understanding.nodes.detect_ambiguity_node",
            "detect_ambiguity_node",
        ),
        "route.determine_resources": (
            f"{_NODE_MODULE_ROOT}.tool_routing.nodes.determine_io_resources_node",
            "determine_io_resources_node",
        ),
        "route.select_tool": (
            f"{_NODE_MODULE_ROOT}.tool_routing.nodes.select_tool_if_needed_node",
            "select_tool_if_needed_node",
        ),
        "retrieval.plan_query": (
            f"{_NODE_MODULE_ROOT}.retrieval.nodes.plan_query_node",
            "plan_query_node",
        ),
        "retrieval.select_evidence": (
            f"{_NODE_MODULE_ROOT}.retrieval.nodes.select_evidence_node",
            "select_evidence_node",
        ),
        "retrieval.assess_sufficiency": (
            f"{_NODE_MODULE_ROOT}.retrieval.nodes.assess_sufficiency_node",
            "assess_sufficiency_node",
        ),
        "analysis.extract_facts": (
            f"{_NODE_MODULE_ROOT}.work_analysis.nodes.extract_work_facts_node",
            "extract_work_facts_node",
        ),
        "analysis.resolve_entity_relations": (
            f"{_NODE_MODULE_ROOT}.work_analysis.nodes.resolve_entity_relations_node",
            "resolve_entity_relations_node",
        ),
        "analysis.resolve_temporal_dependencies": (
            f"{_NODE_MODULE_ROOT}.work_analysis.nodes.resolve_temporal_dependencies_node",
            "resolve_temporal_dependencies_node",
        ),
        "analysis.detect_duplicate_conflict_candidates": (
            f"{_NODE_MODULE_ROOT}.work_analysis.nodes.detect_duplicate_conflict_candidates_node",
            "detect_duplicate_conflict_candidates_node",
        ),
        "analysis.assess_information_gaps": (
            f"{_NODE_MODULE_ROOT}.work_analysis.nodes.assess_information_gaps_node",
            "assess_information_gaps_node",
        ),
        "analysis.assess_operational_risks": (
            f"{_NODE_MODULE_ROOT}.work_analysis.nodes.assess_operational_risks_node",
            "assess_operational_risks_node",
        ),
        "planning.outline_answer": (
            f"{_NODE_MODULE_ROOT}.planning.nodes.outline_answer_node",
            "outline_answer_node",
        ),
        "planning.compose_answer": (
            f"{_NODE_MODULE_ROOT}.planning.nodes.compose_answer_node",
            "compose_answer_node",
        ),
        "planning.draft_action_objective_per_output_route": (
            f"{_NODE_MODULE_ROOT}.planning.nodes.draft_action_objective_per_output_route_node",
            "draft_action_objective_per_output_route_node",
        ),
        "planning.compose_arguments_per_output_route": (
            f"{_NODE_MODULE_ROOT}.planning.nodes.compose_arguments_per_output_route_node",
            "compose_arguments_per_output_route_node",
        ),
        "review.inspect_goal_and_evidence": (
            f"{_NODE_MODULE_ROOT}.review.nodes.inspect_goal_and_evidence_node",
            "inspect_goal_and_evidence_node",
        ),
        "review.inspect_action_scope_route": (
            f"{_NODE_MODULE_ROOT}.review.nodes.inspect_action_scope_and_route_node",
            "inspect_action_scope_and_route_node",
        ),
        "review.inspect_constraints_policy": (
            f"{_NODE_MODULE_ROOT}.review.nodes.inspect_constraints_and_policy_summary_node",
            "inspect_constraints_and_policy_summary_node",
        ),
        "review.recheck": (
            f"{_NODE_MODULE_ROOT}.review.nodes.recheck_affected_dimensions_node",
            "recheck_affected_dimensions_node",
        ),
    }
)

SUBGRAPH_TARGETS: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "request_understanding": (
            f"{_NODE_MODULE_ROOT}.request_understanding.graph",
            "RequestUnderstandingSubgraph",
        ),
        "tool_routing": (f"{_NODE_MODULE_ROOT}.tool_routing.graph", "ToolRoutingSubgraph"),
        "retrieval": (f"{_NODE_MODULE_ROOT}.retrieval.graph", "RetrievalSubgraph"),
        "work_analysis": (f"{_NODE_MODULE_ROOT}.work_analysis.graph", "WorkAnalysisSubgraph"),
        "planning": (f"{_NODE_MODULE_ROOT}.planning.graph", "PlanningSubgraph"),
        "review": (f"{_NODE_MODULE_ROOT}.review.graph", "ReviewSubgraph"),
    }
)

MAIN_PROFILE_TARGETS: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "single_baseline": (
            "google_work_agent.adapters.langgraph.profiles.single_baseline",
            "build_single_baseline_graph",
        ),
        "three_stage": (
            "google_work_agent.adapters.langgraph.profiles.three_stage",
            "build_three_stage_graph",
        ),
        "six_role_baseline": (
            "google_work_agent.adapters.langgraph.profiles.six_role_baseline",
            "build_six_role_baseline_graph",
        ),
    }
)


def resolve_target(target: ExperimentTargetV1) -> ResolvedTarget:
    registry = {
        "NODE": NODE_TARGETS,
        "SUBGRAPH": SUBGRAPH_TARGETS,
        "MAIN_PROFILE": MAIN_PROFILE_TARGETS,
    }[target.target_kind]
    entry = registry.get(target.target_id)
    if entry is None:
        raise TargetResolutionError(f"unknown {target.target_kind} target: {target.target_id}")
    module, symbol = entry
    return ResolvedTarget(target.target_kind, target.target_id, module, symbol)


__all__ = [
    "MAIN_PROFILE_TARGETS",
    "NODE_TARGETS",
    "SUBGRAPH_TARGETS",
    "ResolvedTarget",
    "TargetResolutionError",
    "resolve_target",
]
