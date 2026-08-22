"""Owner-local intermediate contracts for atomic Work Analysis operations."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkAmbiguityV1,
    WorkFactV1,
    WorkRelationV1,
    WorkRiskV1,
)


class WorkRelationCandidateV1(TypedDict):
    relation_type: str
    left_ref: str
    right_ref: str
    evidence_refs: list[str]


class WorkAnalysisSemanticInputV1(TypedDict):
    user_request: str
    request_intent: dict[str, object]
    evidence: list[dict[str, object]]
    confirmation_response: NotRequired[dict[str, object]]


class InformationGapAssessmentV1(TypedDict):
    disposition: Literal[
        "COMPLETE",
        "NEEDS_MORE_DATA",
        "NEEDS_CONFIRMATION",
        "ROUTE_RECONSIDERATION_REQUIRED",
        "BLOCKED",
    ]
    ambiguities: list[WorkAmbiguityV1]
    evidence_refs: list[str]
    needs: NotRequired[list[dict[str, object]]]
    question: NotRequired[str]
    options: NotRequired[list[str]]
    reason_codes: NotRequired[list[str]]


class OperationalRiskAssessmentV1(TypedDict):
    risks: list[WorkRiskV1]
    evidence_refs: list[str]


class WorkAnalysisAssemblyInputV1(TypedDict):
    work_facts: list[WorkFactV1]
    validated_relations: list[WorkRelationV1]
    ambiguities: list[WorkAmbiguityV1]
    risks: list[WorkRiskV1]
    evidence_refs: list[str]
