from __future__ import annotations

import sqlite3

import pytest

from google_work_agent.application.use_cases.run.start_run import StartRunHandler
from google_work_agent.domain import RunStatus
from google_work_agent.ports.models import RunRecord
from tests.unit.application.test_start_run_receipt_recovery import (
    _UnitOfWork,
    _command,
    _handler,
    _received,
)


def test_same_command_id_different_hash_is_conflict_without_domain_mutation() -> None:
    uow = _UnitOfWork()
    original = _command(request_hash="hash-1")
    uow.command_receipts.record = _received(original)

    result = _handler(uow)(_command(request_hash="hash-2"))

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

    result = _handler(uow)(_command())

    assert result.applied is False
    assert result.conflict_detail == "conversation already has an open run"
    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.workflow_handoffs.stage_count == 0
    assert uow.command_receipts.finish_count == 1


def test_insert_integrity_race_reconciles_to_open_run_conflict() -> None:
    uow = _UnitOfWork()
    original_create = uow.runs.create

    def racing_create(run: object) -> None:
        uow.runs.records["racing-run"] = RunRecord(
            id="racing-run",
            conversation_id="conversation-1",
            status=RunStatus.CREATED,
            version=0,
            started_at_ms=19,
            finished_at_ms=None,
        )
        raise sqlite3.IntegrityError("open-run unique race")

    uow.runs.create = racing_create  # type: ignore[method-assign]
    result = _handler(uow)(_command())
    uow.runs.create = original_create  # type: ignore[method-assign]

    assert result.applied is False
    assert result.conflict_detail == "conversation already has an open run"
    assert uow.messages.add_count == 0
    assert uow.workflow_handoffs.stage_count == 0
    assert uow.command_receipts.finish_count == 1


def test_commit_failure_after_handoff_staged_propagates_and_stops_at_commit() -> None:
    uow = _UnitOfWork()

    def fail_commit() -> None:
        raise RuntimeError("commit failure")

    uow.commit = fail_commit  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="commit failure"):
        _handler(uow)(_command())

    assert uow.runs.add_count == 1
    assert uow.workflow_handoffs.stage_count == 1
