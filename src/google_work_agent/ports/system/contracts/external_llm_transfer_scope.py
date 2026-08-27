"""Bounded external-LLM transfer disclosure metadata."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ExternalLlmTransferScopeV1:
    schema_version: Literal[1]
    run_id: str
    scope_revision: int
    scope_hash: str
    source_kinds: tuple[str, ...]
    data_classes: tuple[
        Literal["USER_REQUEST", "RESOURCE_METADATA", "EVIDENCE_EXCERPT", "PLAN_CONTEXT"],
        ...,
    ]

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.scope_revision < 1:
            raise ValueError("invalid external LLM transfer scope version")
        if not self.run_id or not self.scope_hash:
            raise ValueError("external LLM transfer scope identity is required")


__all__ = ["ExternalLlmTransferScopeV1"]
