"""Prepare-retry action wire request."""

from google_work_agent.api.schemas.model import ContractVersionedRequest


class PrepareRetryRequestV2(ContractVersionedRequest):
    command_id: str
    expected_action_version: int
