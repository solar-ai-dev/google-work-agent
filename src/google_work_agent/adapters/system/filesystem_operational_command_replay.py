"""Crash-safe local reservation journal for non-Domain operations."""

from __future__ import annotations

import os
from dataclasses import asdict
from hashlib import sha256
from json import dumps, loads
from pathlib import Path
from uuid import uuid4

from google_work_agent.ports.system.operational_command_replay_port import (
    OperationalCommandContextV1,
    OperationalCommandReplayPort,
    OperationalReplayDecisionV2,
)


class FilesystemOperationalCommandReplayAdapter(OperationalCommandReplayPort):
    """Keep operational idempotency outside the Domain SQLite receipt store."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def reserve_or_replay(
        self, context: OperationalCommandContextV1
    ) -> OperationalReplayDecisionV2:
        path = self._path(context.command_id)
        if not path.exists():
            operation_ref = f"operation:{uuid4()}"
            self._write(
                path,
                {
                    **asdict(context),
                    "operation_ref": operation_ref,
                    "status": "RESERVED",
                    "result_ref": None,
                    "bounded_result": None,
                },
            )
            return OperationalReplayDecisionV2("RESERVED", operation_ref)
        record = loads(path.read_text(encoding="utf-8"))
        if not self._matches(record, context):
            return OperationalReplayDecisionV2("CONFLICT", str(record["operation_ref"]))
        if record["status"] == "COMPLETED":
            return OperationalReplayDecisionV2(
                "COMPLETED",
                str(record["operation_ref"]),
                str(record["result_ref"]),
                record["bounded_result"],
            )
        return OperationalReplayDecisionV2("RECOVER_RESERVED", str(record["operation_ref"]))

    def mark_uncertain(self, context: OperationalCommandContextV1, recovery_ref: str) -> None:
        record = self._current(context)
        record["status"] = "UNCERTAIN"
        record["recovery_ref"] = recovery_ref
        self._write(self._path(context.command_id), record)

    def store_result(
        self,
        context: OperationalCommandContextV1,
        result_ref: str,
        bounded_result: dict[str, object],
    ) -> None:
        record = self._current(context)
        record["status"] = "COMPLETED"
        record["result_ref"] = result_ref
        record["bounded_result"] = bounded_result
        self._write(self._path(context.command_id), record)

    def _current(self, context: OperationalCommandContextV1) -> dict[str, object]:
        path = self._path(context.command_id)
        if not path.exists():
            raise LookupError("operational command has no reservation")
        record = loads(path.read_text(encoding="utf-8"))
        if not self._matches(record, context):
            raise ValueError("operational command reservation does not match context")
        return record

    def _path(self, command_id: str) -> Path:
        return self._root / f"{sha256(command_id.encode()).hexdigest()}.json"

    @staticmethod
    def _matches(record: dict[str, object], context: OperationalCommandContextV1) -> bool:
        return (
            record["request_hash"] == context.request_hash
            and record["operation_kind"] == context.operation_kind
        )

    def _write(self, path: Path, record: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(dumps(record, sort_keys=True, separators=(",", ":")))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
