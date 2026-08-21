"""Reject-action wire request."""

from pydantic import Field

from google_work_agent.api.schemas.common import ContractVersionedRequest


class RejectActionRequestV2(ContractVersionedRequest):
    command_id: str
    expected_version: int
    reason_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )
