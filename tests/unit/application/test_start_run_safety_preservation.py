from __future__ import annotations

import sqlite3

import pytest

from google_work_agent.application.coordinator import QueueBusyError
from google_work_agent.application.use_cases.run.start_run import StartRunHandler
from google_work_agent.domain import RunStatus
from google_work_agent.ports.models import RunRecord
from tests.unit.application.test_start_run_receipt_recovery import (
    _UnitOfWork,
    _command,
    _received,
)


def test_same_command_id_different_hash_is_conflict_without_domain_mutation() -> None:
    uow = _UnitOfWork()
    original = _command(request_hash="hash-1")
    uow.command_receipts.record = _received(original)

    result = StartRunHandler(unit_of_work_factory=lambda: uow, now_ms=lambda: 20)(
        _command(request_hash="hash-2")
    )

    assert result.applied is False
    assert result.request_replayed is True
    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert len(uow.audits.items) == 1
    assert len(uow.traces.items) == 1


def test_existing_open_run_remains_a_start_run_conflict() -> None:
    uow = _UnitOfWork()
    uow.runs.records["other-run"] = RunRecord(
        id="other-run",
        conversation_id="conversation-1",
        status=RunStatus.ANALYZING,
        version=2,
        started_at_ms=5,
        finished_at_ms=None,
    )

    result = StartRunHandler(unit_of_work_factory=lambda: uow, now_ms=lambda: 20)(_command())

    assert result.applied is False
    assert result.conflict_detail == "conversation already has an open run"
    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.finish_count == 1


def test_insert_integrity_race_reconciles_to_open_run_conflict() -> None:
    uow = _UnitOfWork()
    original_add = uow.runs.add

    def racing_add(run: object) -> None:
        uow.runs.records["racing-run"] = RunRecord(
            id="racing-run",
            conversation_id="conversation-1",
            status=RunStatus.CREATED,
            version=0,
            started_at_ms=19,
            finished_at_ms=None,
        )
        raise sqlite3.IntegrityError("open-run unique race")

    uow.runs.add = racing_add  # type: ignore[method-assign]
    result = StartRunHandler(unit_of_work_factory=lambda: uow, now_ms=lambda: 20)(_command())
    uow.runs.add = original_add  # type: ignore[method-assign]

    assert result.applied is False
    assert result.conflict_detail == "conversation already has an open run"
    assert uow.messages.add_count == 0
    assert uow.command_receipts.finish_count == 1


def test_queue_reservation_failure_has_zero_persistence_side_effects() -> None:
    uow = _UnitOfWork()
    handler = StartRunHandler(
        unit_of_work_factory=lambda: uow,
        now_ms=lambda: 20,
        reserve_queue_slot=lambda run_id: False,
    )

    with pytest.raises(QueueBusyError):
        handler(_command())

    assert uow.command_receipts.add_received_count == 0
    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0


def test_failure_after_queue_reservation_releases_slot() -> None:
    uow = _UnitOfWork()
    released: list[str] = []

    def fail_add(run: object) -> None:
        raise RuntimeError("persistence failure")

    uow.runs.add = fail_add  # type: ignore[method-assign]
    handler = StartRunHandler(
        unit_of_work_factory=lambda: uow,
        now_ms=lambda: 20,
        reserve_queue_slot=lambda run_id: True,
        release_queue_slot=released.append,
    )

    with pytest.raises(RuntimeError, match="persistence failure"):
        handler(_command())

    assert released == ["run-1"]


def test_commit_failure_releases_reserved_queue_slot() -> None:
    uow = _UnitOfWork()
    released: list[str] = []

    def fail_commit() -> None:
        raise RuntimeError("commit failure")

    uow.commit = fail_commit  # type: ignore[method-assign]
    handler = StartRunHandler(
        unit_of_work_factory=lambda: uow,
        now_ms=lambda: 20,
        reserve_queue_slot=lambda run_id: True,
        release_queue_slot=released.append,
    )

    with pytest.raises(RuntimeError, match="commit failure"):
        handler(_command())

    assert released == ["run-1"]
