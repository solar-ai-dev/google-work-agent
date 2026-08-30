"""Owner-local Planning semantic contracts for the r8.6 responsibility split."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol, Required, TypedDict


class AnswerOutlineV1(TypedDict):
    sections: list[str]
    evidence_refs: list[str]


class PlanningAnswerConfirmationV1(TypedDict):
    disposition: Required[Literal["NEEDS_CONFIRMATION"]]
    question: str
    options: list[str]
    reason_codes: list[str]


class AnswerDraftCandidateV2(TypedDict):
    schema_version: Required[Literal[2]]
    answer: str
    evidence_refs: list[str]


class ActionObjectiveCandidateV1(TypedDict):
    schema_version: Required[Literal[1]]
    route_id: str
    objective: str
    target_semantics: str
    scope_constraints: list[str]
    evidence_refs: list[str]


class ToolArgumentCandidateV1(TypedDict):
    schema_version: int
    route_id: str
    arguments: dict[str, object]
    evidence_refs: list[str]


PlanningDisposition = Literal["ANSWER", "ACTION"]


class PlanningSemanticInvoker(Protocol):
    def __call__(
        self,
        prompt_id: str,
        prompt_input: Mapping[str, object],
    ) -> Mapping[str, object]: ...
