"""Resolve-recovery wire request."""

from typing import Literal

from google_work_agent.api.schemas.common import ContractVersionedRequest


class ResolveRecoveryRequestV1(ContractVersionedRequest):
    command_id: str
    expected_version: int
    action_id: str
    resolution_kind: Literal["ACCEPT_PARTIAL", "CREATE_CORRECTIVE_PLAN", "FAIL"]
