"""Conversation domain model."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Conversation:
    id: str
    account_id: str
    title: str
    created_at_ms: int
    updated_at_ms: int
