"""Canonical semantic metadata for one registered Connector Tool."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from google_work_agent.domain.action.model import (
    ApprovalRequirement,
    EffectType,
    RecoveryPolicy,
    VerificationPolicy,
)

ToolEffect = Literal["READ", "CREATE", "UPDATE", "SEND", "DELETE"]
RetryClass = Literal["READ_BOUNDED", "WRITE_NO_AUTO_RETRY"]
VerificationStrategy = Literal["NONE", "GET_COMPARE", "GET_ABSENT", "SENT_LOOKUP"]
RecoveryStrategy = Literal["NONE", "GET_TARGET", "RESOURCE_SEARCH", "MESSAGE_SEARCH"]


@dataclass(frozen=True, slots=True)
class SignedToolRegistryEntryV1:
    """The single Core-side semantic authority for one Connector Tool."""

    schema_version: Literal[1]
    connector_id: str
    resource_type: str
    tool_id: str
    effect: ToolEffect
    required_scopes: tuple[str, ...]
    input_schema_ref: str
    output_schema_ref: str
    retry_class: RetryClass
    verification_strategy: VerificationStrategy
    recovery_strategy: RecoveryStrategy

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported SignedToolRegistryEntryV1 schema_version")
        for field_name in (
            "connector_id",
            "resource_type",
            "tool_id",
            "input_schema_ref",
            "output_schema_ref",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} is required")
        if not self.required_scopes:
            raise ValueError("required_scopes must not be empty")
        if any(not scope.strip() for scope in self.required_scopes):
            raise ValueError("required_scopes must contain only nonblank values")
        if len(set(self.required_scopes)) != len(self.required_scopes):
            raise ValueError("required_scopes must not contain duplicates")
        if self.effect not in {"READ", "CREATE", "UPDATE", "SEND", "DELETE"}:
            raise ValueError("unsupported tool effect")
        if self.retry_class not in {"READ_BOUNDED", "WRITE_NO_AUTO_RETRY"}:
            raise ValueError("unsupported retry_class")
        if self.verification_strategy not in {
            "NONE",
            "GET_COMPARE",
            "GET_ABSENT",
            "SENT_LOOKUP",
        }:
            raise ValueError("unsupported verification_strategy")
        if self.recovery_strategy not in {
            "NONE",
            "GET_TARGET",
            "RESOURCE_SEARCH",
            "MESSAGE_SEARCH",
        }:
            raise ValueError("unsupported recovery_strategy")
        if self.effect == "READ" and self.retry_class != "READ_BOUNDED":
            raise ValueError("READ tools require READ_BOUNDED retry_class")
        if self.effect != "READ" and self.retry_class != "WRITE_NO_AUTO_RETRY":
            raise ValueError("write tools require WRITE_NO_AUTO_RETRY retry_class")

    @property
    def registry_entry_hash(self) -> str:
        return sha256(
            json.dumps(self.to_manifest_value(), separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()

    def to_manifest_value(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "connector_id": self.connector_id,
            "resource_type": self.resource_type,
            "tool_id": self.tool_id,
            "effect": self.effect,
            "required_scopes": list(self.required_scopes),
            "input_schema_ref": self.input_schema_ref,
            "output_schema_ref": self.output_schema_ref,
            "retry_class": self.retry_class,
            "verification_strategy": self.verification_strategy,
            "recovery_strategy": self.recovery_strategy,
        }

    # Existing Application policy consumers use these deterministic projections.
    # They derive from the canonical fields and therefore are not a second registry.
    @property
    def tool_name(self) -> str:
        return self.tool_id

    @property
    def effect_type(self) -> EffectType:
        return EffectType(self.effect)

    @property
    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.NONE if self.effect == "READ" else ApprovalRequirement.REQUIRED

    @property
    def verification_policy(self) -> VerificationPolicy:
        return VerificationPolicy(self.verification_strategy)

    @property
    def recovery_policy(self) -> RecoveryPolicy:
        return RecoveryPolicy(self.recovery_strategy)

    @property
    def scope(self) -> str:
        return self.required_scopes[0]

    @property
    def retryable(self) -> bool:
        return self.retry_class == "READ_BOUNDED"

    @property
    def input_schema_version(self) -> str:
        return self.input_schema_ref

    @property
    def output_schema_version(self) -> str:
        return self.output_schema_ref

    @property
    def registry_version(self) -> str:
        return "2026-08-06.p0"

    @property
    def tool_schema_hash(self) -> str:
        return self.registry_entry_hash

    @property
    def modify_patchable_fields(self) -> frozenset[str]:
        return _MODIFY_PATCHABLE_FIELDS.get(self.tool_id, frozenset())


_MODIFY_PATCHABLE_FIELDS: dict[str, frozenset[str]] = {
    "gmail_create_draft": frozenset({"to", "cc", "subject", "body", "attachments"}),
    "gmail_update_draft": frozenset({"to", "cc", "subject", "body", "attachments"}),
    "tasks_create_task": frozenset({"title", "notes", "due"}),
    "tasks_update_task": frozenset({"title", "notes", "due"}),
    "calendar_create_event": frozenset({"title", "start", "end", "description"}),
    "calendar_update_event": frozenset({"title", "start", "end", "description"}),
}


__all__ = [
    "RecoveryStrategy",
    "RetryClass",
    "SignedToolRegistryEntryV1",
    "ToolEffect",
    "VerificationStrategy",
]
