"""Typed request for a cross-agent additional-acquisition handoff."""

from typing import Literal, Required, TypedDict


class AdditionalAcquisitionRequestV1(TypedDict):
    """Structured request for another Stage 5 source-planning round."""

    schema_version: Required[Literal[1]]
    origin_phase: str
    origin_result: str
    missing_slots: list[str]
    missing_information: list[str]
    evidence_refs: list[str]
    reason_codes: list[str]
