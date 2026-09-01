"""Owner-local intermediate contracts for atomic Work Analysis operations."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkAmbiguityV1,
    WorkRiskV1,
)
from google_work_agent.ports.system.contracts.workflow_signal import (
    RetrievalNeedV1,
)


class WorkAnalysisSemanticInputV1(TypedDict):
    user_request: str
    request_intent: dict[str, object]
    evidence: list[dict[str, object]]
    availability_results: NotRequired[list[dict[str, object]]]
    confirmation_response: NotRequired[dict[str, object]]


class CurrentSourceRelationV1(TypedDict):
    """Deterministically validated current-Source relation truth."""

    relation_id: str
    kind: Literal["DUPLICATES", "CONFLICTS_WITH"]
    source_fact_id: str
    target_fact_id: str
    evidence_refs: list[str]


class InformationGapAssessmentV1(TypedDict):
    disposition: Literal[
        "COMPLETE",
        "NEEDS_MORE_DATA",
        "NEEDS_CONFIRMATION",
        "ROUTE_RECONSIDERATION_REQUIRED",
        "BLOCKED",
    ]
    ambiguities: list[WorkAmbiguityV1]
    retrieval_needs: list[RetrievalNeedV1]
    evidence_refs: list[str]
    question: NotRequired[str]
    options: NotRequired[list[str]]
    reason_codes: NotRequired[list[str]]


class OperationalRiskAssessmentV1(TypedDict):
    risks: list[WorkRiskV1]
    action_necessity_candidate: Literal["REQUIRED", "NOT_REQUIRED", "UNDETERMINED"]
    action_necessity_reason: str | None
    evidence_refs: list[str]
