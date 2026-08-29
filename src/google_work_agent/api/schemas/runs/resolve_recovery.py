"""Resolve-recovery wire request."""

from google_work_agent.api.schemas.model import ContractVersionedRequest
from google_work_agent.api.schemas.runs.recovery import (
    RecoveryResolutionKindV1,
    RecoveryTargetV1,
)


class ResolveRecoveryRequestV1(ContractVersionedRequest):
    command_id: str
    expected_version: int
    target: RecoveryTargetV1
    resolution_kind: RecoveryResolutionKindV1
