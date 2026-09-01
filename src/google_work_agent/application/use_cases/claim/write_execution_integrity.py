"""Claim-owner-local integrity helpers for write execution."""

from __future__ import annotations

from google_work_agent.domain.canonical import calculate_canonical_json_hash


def calculate_recovery_fingerprint(
    *, tool_name: str, arguments_hash: str, source_snapshot_hash: str
) -> str:
    return calculate_canonical_json_hash(
        {
            "tool_name": tool_name,
            "arguments_hash": arguments_hash,
            "source_snapshot_hash": source_snapshot_hash,
        }
    )
