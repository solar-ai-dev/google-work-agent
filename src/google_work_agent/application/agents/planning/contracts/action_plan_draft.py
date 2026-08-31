"""Owner-local contracts for deterministic Planning assembly."""

from __future__ import annotations

from typing import Literal, Required, TypedDict

from google_work_agent.application.agents.state_artifact import StateArtifactMetaV1
from google_work_agent.application.agents.state_artifact import (
    StateArtifactRefV1 as StateArtifactRefV1,
)


class PlanningActionSeedV1(TypedDict):
    action_id: str
    route_id: str
    tool_id: str
    effect: Literal["CREATE", "UPDATE", "SEND", "DELETE"]
    arguments: dict[str, object]
    evidence_refs: list[str]


class ActionDependencyCandidateV1(TypedDict):
    action_id: str
    depends_on_action_id: str
    reason: str


class PlannedActionV2(TypedDict):
    action_id: str
    route_id: str
    tool_id: str
    effect: Literal["CREATE", "UPDATE", "SEND", "DELETE"]
    arguments: dict[str, object]
    evidence_refs: list[str]
    depends_on_action_ids: list[str]


class ActionPlanDraftV2(TypedDict):
    schema_version: Required[Literal[2]]
    meta: StateArtifactMetaV1
    actions: list[PlannedActionV2]
