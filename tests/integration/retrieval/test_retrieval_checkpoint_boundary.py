"""Production Retrieval privacy-boundary regressions.

These tests deliberately use LangGraphWorkflowRuntime's SIX production graph
and its real SQLite checkpointer.  Legacy AcquisitionSubgraph direct calls are
not accepted as proof of the release path.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from tests.integration.langgraph.test_runtime import (
    FIXTURE_ROOT,
    FakeGoogleGateway,
    ProductFixtureSnapshotLoader,
    WorkflowOutcome,
    _QueuedLLMRuntime,
    _analysis_output,
    _answer_output,
    _clear_intent,
    _make_runtime,
    _review_output,
    _runtime_active_manifest_path,
    _seed_runtime_database,
    _selection_output,
    _start_request,
    _sufficiency_output,
)

from tests.support.fixtures import ProductFixtureSnapshot

from google_work_agent.application.orchestration.retrieval_evidence_store import (
    EvidenceResolutionError,
)
from google_work_agent.application.orchestration.retrieval_read_cache import (
    ReadResultContinuationError,
)
from google_work_agent.ports import ResourcePage, ResourceType


class _PrivateTaskGateway(FakeGoogleGateway):
    def __init__(
        self, snapshot: ProductFixtureSnapshot, *, private_body: str, continuation: str
    ) -> None:
        super().__init__(snapshot)
        self._boundary_continuation = continuation
        key = (ResourceType.TASK, "task-billing")
        task = self._resources[key]  # noqa: SLF001 - deliberate provider fixture injection
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
            return ResourcePage(items=page.items, next_page_token=self._boundary_continuation)
        return page


def test_production_retrieval_checkpoint_contains_no_raw_provider_or_continuation(
    tmp_path: Path,
) -> None:
    private_body = f"RAW_PROVIDER_PRIVATE_BODY_{uuid4()}"
    continuation = f"RAW_PROVIDER_CONTINUATION_{uuid4()}"
    manifest_path = _runtime_active_manifest_path(tmp_path)
    database_path = _seed_runtime_database(tmp_path)
    checkpoint_path = tmp_path / "checkpoints-retrieval-boundary.db"
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    gateway = _PrivateTaskGateway(
        snapshot,
        private_body=private_body,
        continuation=continuation,
    )
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
        checkpoint_database_path=checkpoint_path,
        prompt_manifest_path=manifest_path,
    )

    result = runtime.start(_start_request())
    assert result.outcome is WorkflowOutcome.COMPLETED

    # Main State/checkpoint-facing values never own either raw value.
    config = runtime._invocation.config_for_thread("thread-1")  # noqa: SLF001
    state = runtime._graph.get_state(config, subgraphs=True)  # noqa: SLF001
    assert private_body not in repr(state.values)
    assert continuation not in repr(state.values)

    # Retrieval's internal selection prompt may consume bounded ranked
    # segments, but downstream Work Analysis/Planning may receive only
    # selected evidence/ref projections.  The unselected private task body
    # must never cross that handoff.
    llm_runtime = cast(_QueuedLLMRuntime, runtime._llm_runtime)  # noqa: SLF001
    downstream_inputs = [
        call["prompt_input"]
        for call in llm_runtime.calls
        if getattr(call["prompt_ref"], "prompt_id", "").startswith(
            ("work_analysis.", "planning.", "review.")
        )
    ]
    assert private_body not in repr(downstream_inputs)
    assert continuation not in repr([call["prompt_input"] for call in llm_runtime.calls])

    # Terminal lifecycle already owns both stores; raw source/evidence from
    # this Run must be unresolvable before a new Run can start.
    with pytest.raises(ReadResultContinuationError):
        runtime._read_result_cache.resolve_resource_snapshot(  # noqa: SLF001
            run_id="run-1", resource_handle="task:task-billing"
        )
    with pytest.raises(EvidenceResolutionError):
        runtime._evidence_store.resolve(  # noqa: SLF001
            run_id="run-1", evidence_refs=["evidence-seg-2"]
        )

    runtime.close()

    for sqlite_path in (checkpoint_path, database_path):
        _assert_sqlite_contains_zero(sqlite_path, private_body)
        _assert_sqlite_contains_zero(sqlite_path, continuation)
        _assert_file_family_contains_zero(sqlite_path, private_body)
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
    encoded = needle.encode("utf-8")
    for path in (
        database_path,
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-shm"),
    ):
        if path.exists():
            assert encoded not in path.read_bytes()


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'
