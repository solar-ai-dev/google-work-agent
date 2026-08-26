"""Project a native runnable checkpoint through the canonical target registry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    ResumeTargetRegistry,
)
from google_work_agent.ports.system.contracts.workflow_binding import GraphProfileIdV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RegisteredResumeTargetRefV2,
    SemanticAgentOwnerIdV1,
)

_SIX_ROLE_ENTRY: dict[str, tuple[SemanticAgentOwnerIdV1, str]] = {
    "request_understanding": ("REQUEST_UNDERSTANDING", "request.identify_goal"),
    "tool_route": ("TOOL_ROUTE", "route.determine_resources"),
    "context_retriever": ("RETRIEVAL", "retrieval.plan_query"),
    "work_analysis": ("WORK_ANALYSIS", "analysis.extract_facts"),
    "planning": ("PLANNING", "planning.outline_answer"),
    "review": ("REVIEW", "review.inspect_goal_and_evidence"),
}

_PHASE_ENTRY: dict[str, tuple[SemanticAgentOwnerIdV1, str]] = {
    "REQUEST_ANALYSIS": ("REQUEST_UNDERSTANDING", "request.identify_goal"),
    "TOOL_ROUTING": ("TOOL_ROUTE", "route.determine_resources"),
    "SOURCE_PLANNING": ("RETRIEVAL", "retrieval.plan_query"),
    "API_ACQUISITION": ("RETRIEVAL", "retrieval.plan_query"),
    "CONTEXT_RETRIEVAL": ("RETRIEVAL", "retrieval.plan_query"),
    "CONTEXT_EVALUATION": ("RETRIEVAL", "retrieval.plan_query"),
    "WORK_ANALYSIS": ("WORK_ANALYSIS", "analysis.extract_facts"),
    "SOLUTION_PLANNING": ("PLANNING", "planning.outline_answer"),
    "PLAN_REVIEW": ("REVIEW", "review.inspect_goal_and_evidence"),
}


@dataclass(frozen=True, slots=True)
class NativeCheckpointTargetResolver:
    registry: ResumeTargetRegistry

    def __call__(
        self,
        checkpoint: Mapping[str, object],
        profile: GraphProfileIdV1,
        graph_version: str,
        fallback: RegisteredResumeTargetRefV2,
    ) -> RegisteredResumeTargetRefV2:
        channels = checkpoint.get("channel_values")
        if not isinstance(channels, Mapping):
            return fallback
        runnable = sorted(
            key.removeprefix("branch:to:")
            for key, value in channels.items()
            if isinstance(key, str) and key.startswith("branch:to:") and bool(value)
        )
        if len(runnable) != 1:
            return fallback
        entry = _SIX_ROLE_ENTRY.get(runnable[0])
        if entry is None and runnable[0] in {
            "single_workflow",
            "stage_one",
            "stage_two",
            "stage_three",
        }:
            phase = channels.get("workflow_phase")
            entry = _PHASE_ENTRY.get(phase) if isinstance(phase, str) else None
        if entry is None:
            return fallback
        owner, node_id = entry
        return self.registry.issue_agent_node(profile, owner, node_id, graph_version)


__all__ = ["NativeCheckpointTargetResolver"]
