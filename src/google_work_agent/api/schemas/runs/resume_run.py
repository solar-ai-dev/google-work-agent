"""Resume-run wire request."""

from typing import Literal

from google_work_agent.api.schemas.common import ContractVersionedRequest


class ResumeRunRequestV2(ContractVersionedRequest):
    command_id: str
    expected_version: int
    resume_kind: Literal["REAUTH_COMPLETED", "SAFE_CHECKPOINT_RESUME", "RECOVERY_RECHECK"]
