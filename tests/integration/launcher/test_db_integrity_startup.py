import asyncio
from pathlib import Path
from typing import Any

import pytest

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.errors import MigrationIntegrityError
from google_work_agent.launcher import dev
from google_work_agent.ports import ReadinessState, RuntimeOperation


def test_build_container_classifies_migration_integrity_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fail_integrity(*args: Any, **kwargs: Any) -> None:
        raise MigrationIntegrityError("startup sqlite quick_check failed")

    monkeypatch.setattr(dev, "apply_migrations", fail_integrity)

    with pytest.raises(dev.CoreInitializationError) as exc_info:
        dev.build_container(runtime_root=tmp_path)

    assert exc_info.value.safe_code == "MIGRATION_FAILED"


def test_migration_failure_enters_safe_mode_and_blocks_writes() -> None:
    def fail_core(**kwargs: Any) -> Any:
        raise dev.CoreInitializationError("MIGRATION_FAILED")

    shell = dev._DeferredApiContainer(
        host=dev.DEFAULT_HOST,
        port=dev.DEFAULT_PORT,
        service_instance_id="test-service",
        bootstrap_secret="test-secret",
        core_builder=fail_core,
    )

    asyncio.run(shell._initialize())

    readiness = shell.readiness_aggregator.evaluate()
    safe_mode = shell.safe_mode_controller.snapshot()
    assert readiness.state is ReadinessState.SAFE_MODE
    assert readiness.checks[0].detail == "MIGRATION_FAILED"
    assert safe_mode.enabled is True
    assert safe_mode.reason_codes == ("MIGRATION_FAILED",)
    assert shell.safe_mode_controller.allows(RuntimeOperation.WRITES) is False
    assert shell.safe_mode_controller.allows(RuntimeOperation.RUN_COMMANDS) is False


def test_full_foreign_key_check_rejects_fk_invalid_latest_database(tmp_path: Path) -> None:
    database_path = tmp_path / "fk-invalid.db"
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute("PRAGMA foreign_keys = OFF;")
        connection.execute(
            """
            INSERT INTO resource_refs (
                id, run_id, connector_id, source, resource_type, resource_id,
                metadata_json, captured_at_ms
            ) VALUES ('orphan-resource', 'missing-run', 'connector-a', 'CALENDAR',
                      'EVENT', 'event-1', '{}', 1);
            """
        )
        connection.commit()
        connection.execute("PRAGMA foreign_keys = ON;")
        assert connection.execute("PRAGMA foreign_key_check;").fetchall()

        with pytest.raises(MigrationIntegrityError, match="foreign_key_check"):
            apply_migrations(connection, now_ms=lambda: 2)
    finally:
        connection.close()


def test_startup_quick_check_failure_is_fail_closed(tmp_path: Path) -> None:
    database_path = tmp_path / "quick-check.db"
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        proxy = _QuickCheckFailureConnection(connection)

        with pytest.raises(MigrationIntegrityError, match="quick_check"):
            apply_migrations(proxy, now_ms=lambda: 2)  # type: ignore[arg-type]
    finally:
        connection.close()


class _QuickCheckFailureConnection:
    """Delegate a real latest DB but inject the corruption result at quick_check."""

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> Any:
        if sql.strip().upper() == "PRAGMA QUICK_CHECK;":
            return _StaticRows([("database disk image is malformed",)])
        return self._delegate.execute(sql, parameters)


class _StaticRows:
    def __init__(self, rows: list[tuple[str]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[str]]:
        return self._rows
