"""Shared Recovery wire identities for Run snapshots, SSE, and commands."""

from typing import Annotated, Literal

from pydantic import Field

from google_work_agent.api.schemas.model import ApiModel

RecoveryResolutionKindV1 = Literal[
    "RECHECK",
    "ACCEPT_PARTIAL",
    "CREATE_CORRECTIVE_PLAN",
    "CANCEL",
    "FAIL",
]


class RunRecoveryTargetV1(ApiModel):
    target_kind: Literal["RUN"]


class ActionRecoveryTargetV1(ApiModel):
    target_kind: Literal["ACTION"]
    action_id: str


RecoveryTargetV1 = Annotated[
    RunRecoveryTargetV1 | ActionRecoveryTargetV1,
    Field(discriminator="target_kind"),
]


class RecoveryUiProjectionV1(ApiModel):
    reason_code: Literal[
        "UNKNOWN_RESULT",
        "VERIFICATION_MISMATCH",
        "CHECKPOINT_MISMATCH",
        "CONTRACT_VIOLATION",
    ]
    message: str
    target: RecoveryTargetV1
    allowed_resolution_kinds: list[RecoveryResolutionKindV1]


__all__ = [
    "ActionRecoveryTargetV1",
    "RecoveryResolutionKindV1",
    "RecoveryTargetV1",
    "RecoveryUiProjectionV1",
    "RunRecoveryTargetV1",
]
