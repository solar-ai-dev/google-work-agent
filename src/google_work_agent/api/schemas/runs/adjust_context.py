"""Context-adjustment wire contracts."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class AdjustContextRequestV1(ApiModel):
    schema_version: Literal[1] = 1
    command_id: str
    plan_id: str
    expected_run_version: int
    expected_retrieval_revision: int
    adjustment_kind: Literal["EXCLUDE_EVIDENCE", "RETRIEVE_MORE"]
    evidence_ids: tuple[str, ...] = ()
    retrieval_query: str | None = None


class AdjustContextResponseV1(ApiModel):
    schema_version: Literal[1]
    applied: bool
    result_code: str
    run_status: str
    run_version: int
    handoff_id: str | None
    conflict_detail: str | None = None


__all__ = ["AdjustContextRequestV1", "AdjustContextResponseV1"]
