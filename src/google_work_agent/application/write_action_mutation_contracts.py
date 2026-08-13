"""Application contracts for write-action review mutations."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ModifyWriteActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    expected_version: int
    arguments_patch: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RejectWriteActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    expected_version: int
    actor_account_id: str | None = None
    reason_code: str | None = None
