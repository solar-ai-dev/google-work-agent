"""Canonical bounded retention persistence port."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RetentionCutoffs:
    terminal_run_ms: int
    message_ms: int
    conversation_ms: int
    trace_ms: int
    audit_ms: int


@dataclass(frozen=True, slots=True)
class RetentionPurgeResult:
    runs: int = 0
    checkpoints: int = 0
    receipts: int = 0
    messages: int = 0
    conversations: int = 0
    traces: int = 0
    audits: int = 0


class RetentionRepository(Protocol):
    def purge_batch(
        self, cutoffs: RetentionCutoffs, batch_limit: int
    ) -> RetentionPurgeResult: ...
