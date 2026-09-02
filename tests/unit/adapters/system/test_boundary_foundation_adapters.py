from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.system.filesystem_backup import FilesystemBackupAdapter
from google_work_agent.adapters.system.filesystem_diagnostics import (
    FilesystemDiagnosticsAdapter,
)
from google_work_agent.adapters.system.memory.run_retrieval_cache import (
    InMemoryRunRetrievalCache,
)
from google_work_agent.adapters.system.memory.sse_event_buffer import InMemorySseEventBuffer
from google_work_agent.adapters.system.process_component_circuit_state import (
    ProcessComponentCircuitStateAdapter,
)
from google_work_agent.adapters.system.process_maintenance_gate import (
    ProcessMaintenanceGateAdapter,
)
from google_work_agent.adapters.system.process_runtime_mode import ProcessRuntimeModeAdapter
from google_work_agent.adapters.system.process_shutdown import ProcessShutdownAdapter
from google_work_agent.adapters.system.sqlite_checkpoint import (
    CheckpointConflictError,
    SqliteCheckpointAdapter,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1
from google_work_agent.ports.system.backup_port import MaintenanceWindow
from google_work_agent.ports.system.component_circuit_state_port import ComponentCircuitKey
from google_work_agent.ports.system.contracts.external_llm_transfer_scope import (
    ExternalLlmTransferScopeV1,
)
from google_work_agent.ports.system.run_retrieval_cache_port import RunRetrievalCacheEntryV1
from google_work_agent.ports.system.sse_event_buffer_port import RunSseEventV1


@dataclass(frozen=True)
class _Clock:
    value: int = 1_000

    def now_ms(self) -> int:
        return self.value


@dataclass
class _MaintenanceGate:
    restore_running: bool = False

    def snapshot(self) -> MaintenanceWindow:
        return MaintenanceWindow(False, False, self.restore_running)

    def try_begin_restore(self) -> bool:
        if self.restore_running:
            return False
        self.restore_running = True
        return True

    def end_restore(self) -> None:
        self.restore_running = False


@dataclass
class _ShutdownComponent:
    calls: list[str]

    def stop_accepting_commands(self) -> None:
        self.calls.append("stop_accepting_commands")

    def stop_accepting(self) -> None:
        self.calls.append("stop_accepting")

    def shutdown(self, timeout_seconds: float) -> None:
        self.calls.append(f"shutdown:{timeout_seconds}")

    def flush_or_checkpoint(self) -> None:
        self.calls.append("flush_or_checkpoint")

    def flush(self) -> None:
        self.calls.append("flush")

    def checkpoint_wal(self) -> None:
        self.calls.append("checkpoint_wal")

    def close(self) -> None:
        self.calls.append("close")

    def invalidate_all(self) -> None:
        self.calls.append("invalidate_all")


def test_runtime_mode_is__process_local_idempotent__and_conflict_safe() -> None:
    adapter = ProcessRuntimeModeAdapter("AUTO")

    assert adapter.set_requested_mode("LOCAL_GPU", "mode-op-1") == "LOCAL_GPU"
    assert adapter.reconcile_update("mode-op-1", "LOCAL_GPU").status == "COMPLETED"
    assert adapter.reconcile_update("missing", "API_LLM").status == "SAFE_TO_RETRY"
    with pytest.raises(ValueError, match="different runtime mode"):
        adapter.set_requested_mode("API_LLM", "mode-op-1")


def test_retrieval_cache__returns_every__canonical_resolution_status() -> None:
    cache = InMemoryRunRetrievalCache()
    read_result = ConnectorReadResultV1(1, "gmail_search_threads", "req-1", {}, None, 1)
    found_entry = RunRetrievalCacheEntryV1(
        1, "handle-1", "run-1", "route-1", "query-hash-1", read_result, False
    )
    exhausted_entry = RunRetrievalCacheEntryV1(
        1, "handle-2", "run-1", "route-1", "query-hash-1", read_result, True
    )
    cache.put_read_result(found_entry)
    cache.put_read_result(exhausted_entry)

    resolve = cache.resolve_read_result
    assert resolve("missing", "run-1", "route-1", "query-hash-1").status == "MISSING"
    assert resolve("handle-1", "run-2", "route-1", "query-hash-1").status == "CROSS_RUN"
    assert resolve("handle-1", "run-1", "route-2", "query-hash-1").status == "BINDING_MISMATCH"
    assert resolve("handle-2", "run-1", "route-1", "query-hash-1").status == "EXHAUSTED"
    assert resolve("handle-1", "run-1", "route-1", "query-hash-1").status == "FOUND"
    cache.discard_run("run-1")
    assert resolve("handle-1", "run-1", "route-1", "query-hash-1").status == "MISSING"


def test_component_circuit__opens_at_threshold__and_success_resets() -> None:
    adapter = ProcessComponentCircuitStateAdapter(failure_threshold=2, open_duration_ms=500)
    key = ComponentCircuitKey(1, "CONNECTOR", "google_workspace", None)

    first = adapter.record_technical_failure(key, "TIMEOUT", 1_000)
    opened = adapter.record_technical_failure(key, "TIMEOUT", 1_100)
    reset = adapter.record_success(key, 1_200)

    assert first.state == "CLOSED"
    assert opened.state == "OPEN"
    assert opened.retry_at_ms == 1_600
    assert reset.state == "CLOSED"
    assert reset.consecutive_technical_failures == 0


def test_sse_buffer__preserves_typed_events_replays_expires__cursor_and_clears() -> None:
    buffer = InMemorySseEventBuffer(service_instance_id="service-1", capacity_per_run=2)
    for index in range(3):
        buffer.append(
            RunSseEventV1(
                schema_version=1,
                event_id="caller-value-is-replaced",
                run_id="run-1",
                action_id=None,
                occurred_at_ms=index,
                event_type="run_status",
                payload={"status": "ANALYZING", "snapshot_version": index},
                projection_version=1,
            )
        )

    page = buffer.list_after("run-1", None, 10)
    assert [event.event_id for event in page.events] == ["service-1:2", "service-1:3"]
    assert page.events[0].payload.snapshot_version == 1
    assert buffer.list_after("run-1", "service-1:1", 10).cursor_status == "OK"
    assert buffer.list_after("run-1", "other:1", 10).cursor_status == "CURSOR_EXPIRED"
    buffer.clear_run("run-1")
    assert buffer.list_after("run-1", None, 10).events == ()


def test_diagnostics_bundle__is_sanitized__bounded_and_replayable(tmp_path: Path) -> None:
    adapter = FilesystemDiagnosticsAdapter(
        collect_snapshot=lambda: {"status": "ok", "api_key": "secret"},
        diagnostics_dir=tmp_path,
        now_ms=lambda: 1_000,
        max_bundle_bytes=1_024,
    )

    first = adapter.create_bundle("RUN", "run-1", "diagnostics-op-1")
    replay = adapter.create_bundle("RUN", "run-1", "diagnostics-op-1")
    stored = json.loads((tmp_path / f"{first.bundle_ref}.json").read_text(encoding="utf-8"))

    assert replay == first
    assert stored["snapshot"]["api_key"] == "[REDACTED]"
    assert adapter.reconcile_bundle("diagnostics-op-1").status == "COMPLETED"


def test_backup_create_restore__and_reconciliation_are__operation_ref_safe(tmp_path: Path) -> None:
    database_path = tmp_path / "app.sqlite3"
    connection = connect_sqlite(database_path)
    try:
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample VALUES ('original')")
    finally:
        connection.close()
    adapter = FilesystemBackupAdapter(
        database_path=database_path,
        backups_dir=tmp_path / "backups",
        clock=_Clock(),
        maintenance_gate=_MaintenanceGate(),
        release_version="test",
        domain_contract_version="test",
        schema_version="0019",
        supported_restore_schema_versions=("0018", "0019"),
    )

    backup = adapter.create_backup("backup-op-1")
    assert adapter.create_backup("backup-op-1") == backup
    assert adapter.reconcile_backup("backup-op-1").status == "COMPLETED"
    connection = connect_sqlite(database_path)
    try:
        connection.execute("UPDATE sample SET value='changed'")
    finally:
        connection.close()

    restored = adapter.restore_backup(backup.backup_ref, "restore-op-1")
    assert restored.status == "RESTORED"
    assert adapter.reconcile_restore(backup.backup_ref, "restore-op-1").status == "COMPLETED"
    connection = connect_sqlite(database_path)
    try:
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "original"
    finally:
        connection.close()


def test_process_maintenance_gate__consumes_live_state__and_serializes_restore() -> None:
    active = False
    gate = ProcessMaintenanceGateAdapter(has_active_write=lambda: active)

    assert gate.try_begin_restore() is True
    assert gate.snapshot().restore_running is True
    assert gate.try_begin_restore() is False
    gate.end_restore()
    active = True
    assert gate.try_begin_restore() is False
    assert gate.snapshot().has_active_write is True


def test_shutdown_acceptance__replays_and__reconciles_without_reexecuting(tmp_path: Path) -> None:
    calls: list[str] = []
    component = _ShutdownComponent(calls)
    adapter = ProcessShutdownAdapter(
        command_gate=component,
        coordinator=component,
        workflow_runtime=component,
        observability=component,
        persistence=component,
        mcp_transport=component,
        sessions=component,
        clock=_Clock(),
        marker_path=tmp_path / "shutdown.json",
        timeout_seconds=2,
    )

    first = adapter.request_shutdown("shutdown-op-1")
    call_count = len(calls)
    replay = adapter.request_shutdown("shutdown-op-1")

    assert first.accepted is True and replay == first
    assert len(calls) == call_count
    assert adapter.reconcile_shutdown("shutdown-op-1").status == "COMPLETED"


def test_checkpoint_external_llm__scope_is_typed__and_revision_monotonic(tmp_path: Path) -> None:
    database_path = tmp_path / "checkpoint.sqlite3"
    with connect_sqlite(database_path) as connection:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            """INSERT INTO google_accounts (id, email, display_name, connected_at_ms)
            VALUES ('account-1', 'user@example.com', 'User', 1)"""
        )
        connection.execute(
            """INSERT INTO conversations
            (id, account_id, title, created_at_ms, updated_at_ms)
            VALUES ('conversation-1', 'account-1', 'Test', 1, 1)"""
        )
        connection.execute(
            """INSERT INTO runs
            (id, conversation_id, entry_mode, status, langgraph_thread_id,
             requested_mode, budget_json, started_at_ms)
            VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', 'CREATED',
                    'thread-1', 'AUTO', '{}', 1)"""
        )
    adapter = SqliteCheckpointAdapter(database_path, now_ms=lambda: 1_000)
    scope = ExternalLlmTransferScopeV1(
        1,
        "run-1",
        1,
        "scope-hash-1",
        ["USER"],
        ["USER_REQUEST", "EVIDENCE_EXCERPT"],
    )
    try:
        adapter.store_external_llm_scope(scope)
        assert adapter.load_external_llm_scope("run-1") == scope
        with pytest.raises(CheckpointConflictError, match="conflicts"):
            adapter.store_external_llm_scope(
                ExternalLlmTransferScopeV1(1, "run-1", 1, "different", ["USER"], ["USER_REQUEST"])
            )
    finally:
        adapter.close()
