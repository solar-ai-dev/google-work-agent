"""Canonical V2 State Artifact DTOs shared across post-Retrieval capabilities.

These types are data contracts only. Candidate validation, deterministic policy
checks, and workflow dispositions remain owned by their respective capabilities.
"""

from __future__ import annotations

from typing import Literal, Required, TypedDict

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkAmbiguityV1,
    WorkAnalysisResultV2,
    WorkFactV1,
    WorkRelationV1,
    WorkRiskV1,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    StateArtifactMetaV1,
)


class AnswerDraftV2(TypedDict):
    schema_version: Required[Literal[2]]
    meta: StateArtifactMetaV1
    answer: str
    evidence_refs: list[str]


__all__ = [
    "AnswerDraftV2",
    "WorkAmbiguityV1",
    "WorkAnalysisResultV2",
    "WorkFactV1",
    "WorkRelationV1",
    "WorkRiskV1",
]
