"""Production Retrieval cache privacy, cleanup, and process-loss regression."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import uuid4

from google_work_agent.adapters.system.memory.run_retrieval_cache import (
    InMemoryRunRetrievalCache,
)
from google_work_agent.ports.connector.contracts.google_workspace import (
    ResourcePage,
    ResourceType,
)
from google_work_agent.ports.system.run_retrieval_cache_port import RunRetrievalCacheEntryV1
from tests.integration.langgraph.test_runtime import (
    FIXTURE_ROOT,
    FakeGoogleGateway,
    ProductFixtureSnapshotLoader,
    WorkflowOutcome,
    _analysis_output,
    _answer_output,
    _clear_intent,
    _make_runtime,
    _QueuedLLMRuntime,
    _review_output,
    _runtime_active_manifest_path,
    _seed_runtime_database,
    _selection_output,
    _start_request,
    _sufficiency_output,
)
from tests.support.checkpoint import sqlite_checkpoint
from tests.support.fixtures import ProductFixtureSnapshot


class _RecordingCache(InMemoryRunRetrievalCache):
    def __init__(self) -> None:
        super().__init__()
        self.bindings: list[tuple[str, str, str, str]] = []

    def put_read_result(self, entry: RunRetrievalCacheEntryV1) -> str:
        self.bindings.append(
            (
                entry.read_result_handle,
                entry.run_id,
                entry.route_id,
                entry.query_identity_hash,
            )
        )
        return super().put_read_result(entry)


class _PrivateTaskGateway(FakeGoogleGateway):
    def __init__(
        self, snapshot: ProductFixtureSnapshot, *, private_body: str, continuation: str
    ) -> None:
        super().__init__(snapshot)
        self._continuation = continuation
        key = (ResourceType.TASK, "task-billing")
        task = self._resources[key]  # noqa: SLF001 - provider fixture injection
        self._resources[key] = replace(  # noqa: SLF001
            task,
            payload={
                **task.payload,
                "notes": private_body,
                "provider_private_blob": {"body": private_body},
            },
        )

    def list_tasks(
        self,
        *,
        task_list_id: str,
        page_token: str | None,
        page_size: int,
        show_completed: bool = False,
        show_hidden: bool = False,
        show_deleted: bool = False,
    ) -> ResourcePage:
        page = super().list_tasks(
            task_list_id=task_list_id,
            page_token=page_token,
            page_size=page_size,
            show_completed=show_completed,
            show_hidden=show_hidden,
            show_deleted=show_deleted,
        )
        if page_token is None:
            return ResourcePage(items=page.items, next_page_token=self._continuation)
        return page


def test_terminal_cleanup_and_process_restart_never_restore_raw_continuation(
    tmp_path: Path,
) -> None:
    private_body = f"RAW_PROVIDER_PRIVATE_BODY_{uuid4()}"
    continuation = f"RAW_PROVIDER_CONTINUATION_{uuid4()}"
    database_path = _seed_runtime_database(tmp_path)
    checkpoint_path = tmp_path / "checkpoints-retrieval-boundary.db"
    gateway = _PrivateTaskGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json"),
        private_body=private_body,
        continuation=continuation,
    )
    cache = _RecordingCache()
    runtime = _make_runtime(
        database_path=database_path,
        llm_payloads=[
            _clear_intent(),
            _selection_output(),
            _sufficiency_output("SUFFICIENT"),
            _analysis_output(),
            _answer_output(),
            _review_output("PASS"),
        ],
        gateway=gateway,
        checkpoint_port=sqlite_checkpoint(checkpoint_path),
        prompt_manifest_path=_runtime_active_manifest_path(tmp_path),
        retrieval_cache=cache,
    )

    try:
        result = runtime.start(_start_request())
        assert result.outcome is WorkflowOutcome.COMPLETED
        assert cache.bindings

        config = runtime._invocation.config_for_thread("thread-1")  # noqa: SLF001
        state = runtime._graph.get_state(config, subgraphs=True)  # noqa: SLF001
        assert private_body not in repr(state.values)
        assert continuation not in repr(state.values)

        llm_runtime = cast(_QueuedLLMRuntime, runtime._llm_runtime)  # noqa: SLF001
        assert continuation not in repr([call["prompt_input"] for call in llm_runtime.calls])

        for binding in cache.bindings:
            assert cache.resolve_read_result(*binding).status == "MISSING"
            assert InMemoryRunRetrievalCache().resolve_read_result(*binding).status == "MISSING"
    finally:
        runtime.close()

    for sqlite_path in (checkpoint_path, database_path):
        _assert_sqlite_contains_zero(sqlite_path, continuation)
        _assert_file_family_contains_zero(sqlite_path, continuation)


def _assert_sqlite_contains_zero(database_path: Path, needle: str) -> None:
    connection = sqlite3.connect(database_path)
    try:
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        matches = 0
        for table in tables:
            quoted_table = _quote_identifier(table)
            columns = [
                str(row[1])
                for row in connection.execute(f"PRAGMA table_info({quoted_table})").fetchall()
            ]
            for column in columns:
                quoted_column = _quote_identifier(column)
                matches += int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {quoted_table} "
                        f"WHERE instr(CAST({quoted_column} AS BLOB), CAST(? AS BLOB)) > 0",
                        (needle,),
                    ).fetchone()[0]
                )
        assert matches == 0
    finally:
        connection.close()


def _assert_file_family_contains_zero(database_path: Path, needle: str) -> None:
    encoded = needle.encode()
    for path in (database_path, Path(f"{database_path}-wal"), Path(f"{database_path}-shm")):
        if path.exists():
            assert encoded not in path.read_bytes()


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'
