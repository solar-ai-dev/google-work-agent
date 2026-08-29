"""Context-adjustment wire contracts."""

from typing import Literal

from pydantic import Field, model_validator

from google_work_agent.api.schemas.model import ApiModel


class AdjustContextRequestV1(ApiModel):
    schema_version: Literal[1] = 1
    command_id: str
    expected_version: int
    expected_retrieval_revision: int
    adjustment_kind: Literal["EXCLUDE_EVIDENCE", "RETRIEVE_MORE"]
    segment_ids: list[str] | None = None
    requested_information: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def validate_discriminated_payload(self) -> "AdjustContextRequestV1":
        segment_ids = self.segment_ids or []
        if len(segment_ids) != len(set(segment_ids)) or any(not item for item in segment_ids):
            raise ValueError("segment_ids must contain unique non-empty values")
        if self.adjustment_kind == "EXCLUDE_EVIDENCE":
            if not segment_ids or self.requested_information is not None:
                raise ValueError(
                    "EXCLUDE_EVIDENCE requires segment_ids and forbids requested_information"
                )
        elif segment_ids or not (self.requested_information or "").strip():
            raise ValueError(
                "RETRIEVE_MORE requires no segment_ids and requested_information"
            )
        return self


class AdjustContextResponseV1(ApiModel):
    schema_version: Literal[1]
    accepted: bool
    current_version: int
    next_phase: Literal["RETRIEVAL"] | None


__all__ = ["AdjustContextRequestV1", "AdjustContextResponseV1"]
