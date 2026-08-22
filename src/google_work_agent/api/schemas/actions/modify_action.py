"""Modify-action wire request."""

from pydantic import Field

from google_work_agent.api.schemas.model import ContractVersionedRequest


class ModifyActionRequestV2(ContractVersionedRequest):
    command_id: str
    expected_version: int
    # Only business fields are accepted; authority metadata remains server-owned.
    arguments_patch: dict[str, object] = Field(default_factory=dict)
