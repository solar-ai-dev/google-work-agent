"""Approval domain model and lifecycle vocabulary."""

from dataclasses import dataclass
from enum import StrEnum


class ApprovalStatusV1(StrEnum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"
    REVOKED = "REVOKED"


class ApprovalCommand(StrEnum):
    EXPIRE_APPROVAL = "EXPIRE_APPROVAL"


@dataclass(frozen=True, slots=True)
class Approval:
    id: str
    action_id: str
    approval_no: int
    action_version: int
    status: ApprovalStatusV1
    approved_by_account_id: str
    approved_by_display: str | None
    arguments_snapshot_json: str
    canonical_arguments_hash: str
    source_snapshot_json: str
    source_snapshot_hash: str
    policy_version: str
    tool_schema_version: str
    idempotency_key: str
    recovery_fingerprint: str
    approved_at_ms: int
    expires_at_ms: int
    consumed_at_ms: int | None
