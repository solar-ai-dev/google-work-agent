"""Project a native runnable checkpoint through the canonical target registry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from google_work_agent.adapters.langgraph.registry.node_registry import (
    RUNTIME_NODE_OWNERS,
)
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    ResumeTargetRegistry,
)
from google_work_agent.ports.system.contracts.workflow_binding import GraphProfileIdV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RegisteredResumeTargetRefV2,
)


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
        if fallback.graph_profile != profile or fallback.graph_version != graph_version:
            raise ValueError("checkpoint fallback profile/version binding is stale")
        self.registry.validate(fallback)
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
        phase = channels.get("workflow_phase")
        node_id = _project_entry_node_id(runnable[0], phase if isinstance(phase, str) else None)
        if node_id is None:
            return fallback
        owner = RUNTIME_NODE_OWNERS[node_id]
        return self.registry.issue_agent_node(profile, owner, node_id, graph_version)


def _project_entry_node_id(runnable: str, phase: str | None) -> str | None:
    """Project native graph position without owning a second target registry."""

    match runnable:
        case "request_understanding":
            return "request.identify_goal"
        case "tool_route":
            return "route.determine_resources"
        case "context_retriever":
            return "retrieval.plan_query"
        case "work_analysis":
            return "analysis.extract_facts"
        case "planning":
            return "planning.outline_answer"
        case "review":
            return "review.inspect_goal_and_evidence"
        case "single_workflow" | "stage_one" | "stage_two" | "stage_three":
            match phase:
                case "REQUEST_ANALYSIS":
                    return "request.identify_goal"
                case "TOOL_ROUTING":
                    return "route.determine_resources"
                case (
                    "SOURCE_PLANNING"
                    | "API_ACQUISITION"
                    | "CONTEXT_RETRIEVAL"
                    | "CONTEXT_EVALUATION"
                ):
                    return "retrieval.plan_query"
                case "WORK_ANALYSIS":
                    return "analysis.extract_facts"
                case "SOLUTION_PLANNING":
                    return "planning.outline_answer"
                case "PLAN_REVIEW":
                    return "review.inspect_goal_and_evidence"
        case _:
            return None
    return None


__all__ = ["NativeCheckpointTargetResolver"]
