"""Typed receipt produced by the Run confirmation boundary."""

from typing import Literal, Required, TypedDict

from google_work_agent.application.agents.state_artifact import StateArtifactMetaV1


class PolicyConfirmationReceiptV1(TypedDict):
    schema_version: Required[Literal[1]]
    meta: StateArtifactMetaV1
    interrupt_id: str
    confirmation_kind: Literal[
        "SCOPE_EXPANSION",
        "DUPLICATE_OVERRIDE",
        "CONFLICT_OVERRIDE",
    ]
    decision: Literal["APPROVED", "DECLINED"]
    semantic_owner_id: Literal["TOOL_ROUTE", "WORK_ANALYSIS"]
    decision_context_hash: str
    affected_route_ids: list[str]
    affected_resource_refs: list[str]
