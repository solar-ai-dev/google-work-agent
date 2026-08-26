"""Canonical application use case for entering Run retrieval."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps, loads

from google_work_agent.domain import ResultCode, RunStatus
from google_work_agent.domain.run.model import RunTransitionRejected
from google_work_agent.domain.run.transitions.begin_retrieval import transition_begin_retrieval
from google_work_agent.domain.run.transitions.run import next_allowed_run_commands
from google_work_agent.ports.models import (
    AuditEventRecord,
    CommandReceiptRecord,
    CommandReceiptStatus,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class BeginRetrievalCommand:
    run_id: str
    expected_version: int
    command_id: str
    request_hash: str


@dataclass(frozen=True, slots=True)
class BeginRetrievalResult:
    applied: bool
    result_code: str
    current_status: str
    current_version: int
    next_allowed_commands: tuple[str, ...]
    conflict_detail: str | None = None


class BeginRetrievalHandler:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: BeginRetrievalCommand) -> BeginRetrievalResult:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return self._replay(unit_of_work, command, existing)
            run = unit_of_work.runs.get(command.run_id)
            if run is None:
                raise LookupError(f"run not found: {command.run_id}")
            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="BeginRetrieval",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            result = self._apply(unit_of_work, command, run.status, run.version)
            if result.applied:
                unit_of_work.audits.add(_audit(command.run_id, command.command_id, now_ms))
            _finish_receipt(unit_of_work, command.command_id, result, now_ms)
            unit_of_work.commit()
            return result

    @staticmethod
    def _apply(
        unit_of_work: UnitOfWork, command: BeginRetrievalCommand, status: RunStatus, version: int
    ) -> BeginRetrievalResult:
        if version != command.expected_version:
            return _result(False, ResultCode.VERSION_CONFLICT, status, version, "version mismatch")
        try:
            next_status = transition_begin_retrieval(status)
        except RunTransitionRejected as error:
            return _result(False, ResultCode.STATE_CONFLICT, status, version, str(error))
        applied = unit_of_work.runs.update_if_version_and_status(
            command.run_id,
            command.expected_version,
            frozenset({status}),
            {"status": next_status.value, "version": version + 1, "finished_at_ms": None},
        )
        if not applied:
            current = unit_of_work.runs.get(command.run_id)
            if current is None:
                raise LookupError(f"run not found: {command.run_id}")
            return _result(
                False,
                ResultCode.VERSION_CONFLICT,
                current.status,
                current.version,
                "compare-and-set rejected the transition",
            )
        return _result(True, ResultCode.TRANSITION_APPLIED, next_status, version + 1)

    @staticmethod
    def _replay(
        unit_of_work: UnitOfWork,
        command: BeginRetrievalCommand,
        receipt: CommandReceiptRecord,
    ) -> BeginRetrievalResult:
        if receipt.request_hash != command.request_hash:
            run = unit_of_work.runs.get(command.run_id)
            return _result(
                False,
                ResultCode.DUPLICATE_COMMAND,
                RunStatus.CREATED if run is None else run.status,
                0 if run is None else run.version,
                "command_id already exists with a different request_hash",
            )
        if receipt.status is CommandReceiptStatus.RECEIVED or receipt.response_json is None:
            raise RuntimeError("RECEIVED receipt requires transaction recovery before replay")
        payload = loads(receipt.response_json)
        payload["next_allowed_commands"] = tuple(payload.get("next_allowed_commands", ()))
        return BeginRetrievalResult(**payload)


def _result(
    applied: bool,
    result_code: ResultCode,
    status: RunStatus,
    version: int,
    conflict_detail: str | None = None,
) -> BeginRetrievalResult:
    return BeginRetrievalResult(
        applied=applied,
        result_code=result_code.value,
        current_status=status.value,
        current_version=version,
        next_allowed_commands=tuple(command.value for command in next_allowed_run_commands(status)),
        conflict_detail=conflict_detail,
    )


def _audit(run_id: str, command_id: str, now_ms: int) -> AuditEventRecord:
    return AuditEventRecord(
        account_id=None,
        run_id=run_id,
        action_id=None,
        actor_type="SYSTEM",
        actor_id="run_lifecycle",
        actor_display="Run lifecycle",
        event_type="RUN_RETRIEVAL_STARTED",
        outcome=ResultCode.TRANSITION_APPLIED.value,
        metadata_json=dumps({"command_id": command_id}, sort_keys=True),
        created_at_ms=now_ms,
    )


def _finish_receipt(
    unit_of_work: UnitOfWork, command_id: str, result: BeginRetrievalResult, now_ms: int
) -> None:
    unit_of_work.command_receipts.finish_json(
        command_id=command_id,
        applied=result.applied,
        result_code=ResultCode(result.result_code),
        result_version=result.current_version,
        response_json=dumps(asdict(result), sort_keys=True),
        completed_at_ms=now_ms,
    )
