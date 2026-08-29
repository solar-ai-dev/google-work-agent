"""Bounded external-LLM transfer disclosure metadata."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ExternalLlmTransferScopeV1:
    schema_version: Literal[1]
    run_id: str
    scope_revision: int
    scope_hash: str
    source_kinds: list[str]
    data_classes: list[
        Literal["USER_REQUEST", "RESOURCE_METADATA", "EVIDENCE_EXCERPT", "PLAN_CONTEXT"],
    ]

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.scope_revision < 1:
            raise ValueError("invalid external LLM transfer scope version")
        if not self.run_id or not self.scope_hash:
            raise ValueError("external LLM transfer scope identity is required")
        if not isinstance(self.source_kinds, list) or not isinstance(self.data_classes, list):
            raise TypeError("external LLM transfer scope collections must be lists")
        if not self.source_kinds or any(not item.strip() for item in self.source_kinds):
            raise ValueError("external LLM source kinds must be non-empty")
        allowed_data_classes = {
            "USER_REQUEST",
            "RESOURCE_METADATA",
            "EVIDENCE_EXCERPT",
            "PLAN_CONTEXT",
        }
        if not self.data_classes or any(
            item not in allowed_data_classes for item in self.data_classes
        ):
            raise ValueError("invalid external LLM data class")


__all__ = ["ExternalLlmTransferScopeV1"]
