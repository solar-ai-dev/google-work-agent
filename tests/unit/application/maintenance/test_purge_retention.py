from types import SimpleNamespace

import pytest

from google_work_agent.application.maintenance.purge_retention import (
    PurgeRetentionCommand,
    PurgeRetentionHandler,
)
from google_work_agent.ports.persistence.retention_repository import (
    RetentionCutoffs,
    RetentionPurgeResult,
)

_DAY_MS = 86_400_000


class _Settings:
    def __init__(self, retention_days: int) -> None:
        self._retention_days = retention_days

    def get(self) -> SimpleNamespace:
        return SimpleNamespace(run_retention_days=self._retention_days)


class _Retention:
    def __init__(self) -> None:
        self.call: tuple[RetentionCutoffs, int] | None = None

    def purge_batch(
        self, cutoffs: RetentionCutoffs, batch_limit: int
    ) -> RetentionPurgeResult:
        self.call = (cutoffs, batch_limit)
        return RetentionPurgeResult(runs=2, traces=3, audits=4)


class _Audits:
    def __init__(self) -> None:
        self.records: list[object] = []

    def append(self, record: object) -> None:
        self.records.append(record)


class _UnitOfWork:
    def __init__(self) -> None:
        self.retention = _Retention()
        self.audits = _Audits()
        self.committed = False

    def __enter__(self) -> "_UnitOfWork":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def commit(self) -> None:
        self.committed = True


def test_purge_retention_derives_configured_and_fixed_audit_cutoffs() -> None:
    unit_of_work = _UnitOfWork()
    now_ms = 100 * _DAY_MS
    handler = PurgeRetentionHandler(
        settings=_Settings(7),  # type: ignore[arg-type]
        unit_of_work_factory=lambda: unit_of_work,  # type: ignore[arg-type]
    )

    result = handler.handle(PurgeRetentionCommand(now_ms=now_ms, batch_limit=25))

    assert result == RetentionPurgeResult(runs=2, traces=3, audits=4)
    assert unit_of_work.retention.call == (
        RetentionCutoffs(
            terminal_run_ms=now_ms - 7 * _DAY_MS,
            message_ms=now_ms - 7 * _DAY_MS,
            conversation_ms=now_ms - 7 * _DAY_MS,
            trace_ms=now_ms - 7 * _DAY_MS,
            audit_ms=now_ms - 90 * _DAY_MS,
        ),
        25,
    )
    assert unit_of_work.committed
    assert len(unit_of_work.audits.records) == 1


@pytest.mark.parametrize("retention_days", [0, 31])
def test_purge_retention_rejects_out_of_policy_setting(retention_days: int) -> None:
    handler = PurgeRetentionHandler(
        settings=_Settings(retention_days),  # type: ignore[arg-type]
        unit_of_work_factory=lambda: _UnitOfWork(),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="retention_days"):
        handler.handle(PurgeRetentionCommand(now_ms=100 * _DAY_MS))
