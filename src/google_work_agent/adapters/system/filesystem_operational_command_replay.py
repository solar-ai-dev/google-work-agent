"""Crash-safe local reservation journal for non-Domain operations."""

from __future__ import annotations

import os
from dataclasses import asdict
from hashlib import sha256
from json import dumps, loads
from pathlib import Path
from typing import cast
from uuid import uuid4

from google_work_agent.ports.system.contracts.operational_command_replay import (
    JsonValue,
    OperationalCommandContextV1,
    OperationalReplayDecisionV2,
)
from google_work_agent.ports.system.operational_command_replay_port import (
    OperationalCommandReplayPort,
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
            operation_ref = self._operation_ref(context)
            record = {
                **asdict(context),
                "operation_ref": operation_ref,
                "status": "RESERVED",
                "result_ref": None,
                "recovery_ref": None,
                "bounded_result": None,
            }
            if self._write_new(path, record):
                return OperationalReplayDecisionV2(
                    decision="PROCEED_NEW",
                    reservation_status="RESERVED",
                    operation_ref=operation_ref,
                    stored_result_ref=None,
                    recovery_ref=None,
                )
        record = loads(path.read_text(encoding="utf-8"))
        if not self._matches(record, context):
            return OperationalReplayDecisionV2(
                decision="CONFLICT",
                reservation_status=None,
                operation_ref=None,
                stored_result_ref=None,
                recovery_ref=None,
            )
        if record["status"] == "COMPLETED":
            return OperationalReplayDecisionV2(
                decision="REPLAY_COMPLETED",
                reservation_status="COMPLETED",
                operation_ref=str(record["operation_ref"]),
                stored_result_ref=str(record["result_ref"]),
                recovery_ref=None,
                bounded_result=cast(JsonValue, record["bounded_result"]),
            )
        return OperationalReplayDecisionV2(
            decision="RECOVER_RESERVED",
            reservation_status="UNCERTAIN" if record["status"] == "UNCERTAIN" else "RESERVED",
            operation_ref=str(record["operation_ref"]),
            stored_result_ref=None,
            recovery_ref=None
            if record.get("recovery_ref") is None
            else str(record["recovery_ref"]),
        )

    def mark_uncertain(self, context: OperationalCommandContextV1, recovery_ref: str) -> None:
        record = self._current(context)
        record["status"] = "UNCERTAIN"
        record["recovery_ref"] = recovery_ref
        self._write(self._path(context.command_id), record)

    def store_result(
        self,
        context: OperationalCommandContextV1,
        result_ref: str,
        bounded_result: JsonValue,
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
        return cast(dict[str, object], record)

    def _path(self, command_id: str) -> Path:
        return self._root / f"{sha256(command_id.encode()).hexdigest()}.json"

    @staticmethod
    def _operation_ref(context: OperationalCommandContextV1) -> str:
        identity = (
            f"{context.command_id}\0{context.operation_kind}\0{context.canonical_request_hash}"
        ).encode()
        return f"operation:{sha256(identity).hexdigest()}"

    @staticmethod
    def _matches(record: dict[str, object], context: OperationalCommandContextV1) -> bool:
        return (
            record["canonical_request_hash"] == context.canonical_request_hash
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

    def _write_new(self, path: Path, record: dict[str, object]) -> bool:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(dumps(record, sort_keys=True, separators=(",", ":")).encode())
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                return False
            return True
        finally:
            temporary.unlink(missing_ok=True)
