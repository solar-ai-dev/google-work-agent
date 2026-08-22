from __future__ import annotations

import pytest

from google_work_agent.application.use_cases.execution_attempt.mark_failed import (
    MarkFailedCommand,
    MarkFailedHandler,
)
from google_work_agent.application.use_cases.execution_attempt.mark_unknown_result import (
    MarkUnknownResultCommand,
    MarkUnknownResultHandler,
)
from google_work_agent.ports import DeliveryCertainty


def _unexpected_uow() -> object:
    raise AssertionError("invalid delivery classification must fail before persistence")


def test_failed_requires_definitive_not_sent() -> None:
    handler = MarkFailedHandler(
        unit_of_work_factory=_unexpected_uow,  # type: ignore[arg-type]
        now_ms=lambda: 1,
    )
    with pytest.raises(ValueError, match="NOT_SENT"):
        handler(
            MarkFailedCommand(
                "cmd-failed",
                "hash",
                "action-1",
                "attempt-1",
                1,
                1,
                DeliveryCertainty.MAY_HAVE_BEEN_SENT,
                "TIMEOUT",
                "uncertain",
            )
        )


def test_unknown_result_rejects_definitive_not_sent() -> None:
    handler = MarkUnknownResultHandler(
        unit_of_work_factory=_unexpected_uow,  # type: ignore[arg-type]
        now_ms=lambda: 1,
    )
    with pytest.raises(ValueError, match="possibly dispatched"):
        handler(
            MarkUnknownResultCommand(
                "cmd-unknown",
                "hash",
                "action-1",
                "attempt-1",
                1,
                1,
                DeliveryCertainty.NOT_SENT,
                "CONNECTION_CLOSED",
                "definitively not sent",
            )
        )
