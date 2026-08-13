"""Application contracts for explicit write approval."""

from dataclasses import dataclass

DEFAULT_APPROVAL_TTL_MS = 30_000


@dataclass(frozen=True, slots=True)
class ApproveWriteActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    expected_version: int
    approved_by_account_id: str
    approved_by_display: str | None
    source_snapshot: dict[str, object]
    approval_id: str
    idempotency_key: str
    ttl_ms: int = DEFAULT_APPROVAL_TTL_MS
    duplicate_acknowledged: bool = False
    calendar_conflict_acknowledged: bool = False
