"""Operations controlled by the process runtime safety boundary."""

from __future__ import annotations

from enum import StrEnum


class RuntimeOperation(StrEnum):
    """Operations evaluated by the runtime safe-mode boundary."""

    SETTINGS = "SETTINGS"
    BACKUP = "BACKUP"
    RESTORE = "RESTORE"
    SHUTDOWN = "SHUTDOWN"
    DIAGNOSTICS = "DIAGNOSTICS"
    RUN_COMMANDS = "RUN_COMMANDS"
    APPROVALS = "APPROVALS"
    WRITES = "WRITES"
