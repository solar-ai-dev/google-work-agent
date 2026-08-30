"""Test-only construction for the concrete checkpoint adapter."""

from pathlib import Path

from google_work_agent.adapters.system.sqlite_checkpoint import SqliteCheckpointAdapter


def sqlite_checkpoint(path: Path) -> SqliteCheckpointAdapter:
    return SqliteCheckpointAdapter(path, now_ms=lambda: 1_000)


__all__ = ["sqlite_checkpoint"]
