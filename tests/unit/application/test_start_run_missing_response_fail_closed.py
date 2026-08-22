from __future__ import annotations

from dataclasses import replace

import pytest

from google_work_agent.application.use_cases.run.start_run import StartRunHandler
from google_work_agent.domain import ResultCode
from google_work_agent.ports.models import CommandReceiptStatus
from tests.unit.application.test_start_run_receipt_recovery import (
    _UnitOfWork,
    _command,
    _received,
)


def test_completed_receipt_without_response_and_without_aggregate_is_not_reapplied() -> None:
    uow = _UnitOfWork()
    command = _command()
    uow.command_receipts.record = replace(
        _received(command),
        status=CommandReceiptStatus.APPLIED,
        result_code=ResultCode.TRANSITION_APPLIED,
        result_version=0,
    )

    with pytest.raises(RuntimeError, match="missing replay response"):
        StartRunHandler(unit_of_work_factory=lambda: uow, now_ms=lambda: 20)(command)

    assert uow.runs.add_count == 0
    assert uow.messages.add_count == 0
    assert uow.command_receipts.finish_count == 0
