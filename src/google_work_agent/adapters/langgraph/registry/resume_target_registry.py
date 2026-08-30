"""Single authority for issuing and validating safe workflow resume targets."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.adapters.langgraph.registry.node_registry import NodeRegistry
from google_work_agent.ports.system.contracts.workflow_binding import GraphProfileIdV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    AgentNodeResumeTargetV2,
    MainControlResumeTargetV2,
    MainResumeStageIdV1,
    RegisteredResumeTargetRefV2,
    SemanticAgentOwnerIdV1,
)

MAIN_RESUME_STAGES: frozenset[MainResumeStageIdV1] = frozenset(
    {
        "RETRIEVAL_ENTRY",
        "PLANNING_ENTRY",
        "REVIEW_ENTRY",
        "PREFLIGHT",
        "READ_EXECUTION",
        "VERIFICATION",
        "RECOVERY",
        "CANCEL_RESOLUTION",
    }
)


@dataclass(frozen=True, slots=True)
class ResumeTargetRegistry:
    node_registry: NodeRegistry
    graph_version: str

    def __post_init__(self) -> None:
        if not self.graph_version:
            raise ValueError("resume target graph version must be non-empty")
        if self.node_registry.graph_version != self.graph_version:
            raise ValueError("node and resume registries must use the same graph version")

    def issue_agent_node(
        self,
        graph_profile: GraphProfileIdV1,
        semantic_owner_id: SemanticAgentOwnerIdV1,
        node_id: str,
        graph_version: str,
    ) -> AgentNodeResumeTargetV2:
        compiled_subgraph_id = self.node_registry.get_required(
            graph_version, graph_profile, semantic_owner_id, node_id
        )
        target = AgentNodeResumeTargetV2(
            kind="AGENT_NODE",
            semantic_owner_id=semantic_owner_id,
            compiled_subgraph_id=compiled_subgraph_id,
            node_id=node_id,
            graph_profile=graph_profile,
            graph_version=graph_version,
        )
        self.validate(target)
        return target

    def issue_main_stage(
        self,
        graph_profile: GraphProfileIdV1,
        stage_id: MainResumeStageIdV1,
        graph_version: str,
    ) -> MainControlResumeTargetV2:
        target = MainControlResumeTargetV2(
            kind="MAIN_CONTROL",
            stage_id=stage_id,
            graph_profile=graph_profile,
            graph_version=graph_version,
        )
        self.validate(target)
        return target

    def validate(self, ref: RegisteredResumeTargetRefV2) -> None:
        if ref.graph_version != self.graph_version:
            raise ValueError("resume target graph version is stale or unknown")
        self.node_registry.require_profile(ref.graph_profile)
        if isinstance(ref, MainControlResumeTargetV2):
            if ref.kind != "MAIN_CONTROL":
                raise ValueError("main resume target kind is invalid")
            if ref.stage_id not in MAIN_RESUME_STAGES:
                raise ValueError("main resume stage is not registered")
            return
        if not isinstance(ref, AgentNodeResumeTargetV2) or ref.kind != "AGENT_NODE":
            raise ValueError("resume target kind is not registered")
        expected = self.node_registry.get_required(
            ref.graph_version,
            ref.graph_profile,
            ref.semantic_owner_id,
            ref.node_id,
        )
        if ref.compiled_subgraph_id != expected:
            raise ValueError("resume target compiled subgraph binding is invalid")


__all__ = ["MAIN_RESUME_STAGES", "ResumeTargetRegistry"]
