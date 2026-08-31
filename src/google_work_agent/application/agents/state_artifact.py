"""Shared lineage contract for canonical Agent State Artifacts."""

from typing import TypedDict


class StateArtifactRefV1(TypedDict):
    artifact_id: str
    revision: int


class StateArtifactMetaV1(TypedDict):
    artifact_id: str
    revision: int
    based_on: list[StateArtifactRefV1]
