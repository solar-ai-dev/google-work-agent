"""Typed metadata for same-Run workflow checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.system.contracts.workflow_binding import GraphProfileIdV1
from google_work_agent.ports.system.contracts.workflow_handoff import RegisteredResumeTargetRefV2


@dataclass(frozen=True, slots=True)
class RetrievalCacheRequirementV1:
    schema_version: Literal[1]
    read_result_handle: str
    route_id: str
    query_identity_hash: str


@dataclass(frozen=True, slots=True)
class GraphCheckpointEnvelopeV1:
    schema_version: Literal[1]
    checkpoint_id: str
    checkpoint_generation: int
    run_id: str
    langgraph_thread_id: str
    graph_profile: GraphProfileIdV1
    graph_version: str
    owner_scope: str
    registered_resume_target: RegisteredResumeTargetRefV2 | None
    applied_handoff_id: str | None
    execution_admission_id: str | None
    active_handoff_id: str | None
    active_handoff_run_sequence: int | None
    retrieval_cache_requirements: tuple[RetrievalCacheRequirementV1, ...]
    created_at_ms: int
    checkpoint_blob: bytes
    pre_reauth_status: RunStatusV1 | None = None

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not self.checkpoint_id:
            raise ValueError("invalid GraphCheckpointEnvelopeV1 identity")
        if self.checkpoint_generation < 1 or self.created_at_ms < 0:
            raise ValueError("invalid GraphCheckpointEnvelopeV1 generation/time")
        if (self.active_handoff_id is None) != (self.active_handoff_run_sequence is None):
            raise ValueError("active handoff lineage must be complete")
        if self.active_handoff_run_sequence is not None and self.active_handoff_run_sequence < 1:
            raise ValueError("active handoff sequence must be positive")
        if self.pre_reauth_status is RunStatusV1.REAUTH_REQUIRED:
            raise ValueError("pre_reauth_status cannot be REAUTH_REQUIRED")
