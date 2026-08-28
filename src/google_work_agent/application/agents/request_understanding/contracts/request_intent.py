from __future__ import annotations

from typing import Literal, Required, TypedDict

ConstraintKindValue = Literal[
    "PERSON", "EMAIL", "DATE", "TIME", "RESOURCE", "SCOPE", "USER_REQUIREMENT"
]
ActionEffectValue = Literal["READ", "CREATE", "UPDATE", "SEND", "DELETE"]


class StateArtifactRefV1(TypedDict):
    artifact_id: str
    revision: int


class StateArtifactMetaV1(TypedDict):
    artifact_id: str
    revision: int
    based_on: list[StateArtifactRefV1]


class ConstraintV1(TypedDict):
    kind: ConstraintKindValue
    field: str
    value: str | list[str]


class AmbiguityV1(TypedDict):
    requires_confirmation: bool
    reason_codes: list[str]
    missing_fields: list[str]


class RequestIntentCandidateV1(TypedDict):
    schema_version: Required[Literal[2]]
    goal: str
    completion_conditions: list[str]
    constraints: list[ConstraintV1]
    requested_effect_hints: list[ActionEffectValue]
    requested_resource_hints: list[str]
    analysis_requirement: Literal["NONE", "REQUIRED"]
    ambiguity: AmbiguityV1


class RequestIntentV2(RequestIntentCandidateV1):
    meta: StateArtifactMetaV1
