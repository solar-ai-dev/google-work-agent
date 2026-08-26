"""Get the persisted execution context for one run."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Row

from google_work_agent.ports import QueryConnectionFactory, SelectedResourceRef


@dataclass(frozen=True, slots=True)
class GetExecutionContextQuery:
    run_id: str


@dataclass(frozen=True, slots=True)
class GetExecutionContextResult:
    run_id: str
    conversation_id: str
    workflow_key: str
    entry_mode: str
    requested_mode: str
    status: str
    version: int
    request_text: str
    selected_resource_ids: tuple[str, ...]
    selected_resources: tuple[SelectedResourceRef, ...] = ()


class GetExecutionContextHandler:
    def __init__(self, *, database_path: Path, connection_factory: QueryConnectionFactory) -> None:
        self._database_path = database_path
        self._connection_factory = connection_factory

    @classmethod
    def from_legacy_query_supplier(
        cls, query_supplier: Callable[[], object]
    ) -> GetExecutionContextHandler:
        query = query_supplier()
        return cls(
            database_path=query._database_path,  # type: ignore[attr-defined]
            connection_factory=query._connection_factory,  # type: ignore[attr-defined]
        )

    def __call__(self, query: GetExecutionContextQuery) -> GetExecutionContextResult | None:
        with self._connection_factory(self._database_path) as connection:
            run_row = connection.execute(
                """
                SELECT id, conversation_id, langgraph_thread_id, entry_mode,
                       requested_mode, status, version
                FROM runs WHERE id = ?;
                """,
                (query.run_id,),
            ).fetchone()
            if run_row is None:
                return None
            message_row = connection.execute(
                """
                SELECT content FROM messages
                WHERE run_id = ? AND role = 'USER'
                ORDER BY created_at_ms ASC, id ASC LIMIT 1;
                """,
                (query.run_id,),
            ).fetchone()
            resource_rows = connection.execute(
                """
                SELECT source, resource_type, resource_id, parent_resource_id
                FROM resource_refs
                WHERE run_id = ?
                ORDER BY connector_id, resource_type, resource_id;
                """,
                (query.run_id,),
            ).fetchall()
        selected_resource_ids = tuple(str(row["resource_id"]) for row in resource_rows)
        selected_resources = tuple(_selected_resource_ref(row) for row in resource_rows)
        return GetExecutionContextResult(
            run_id=str(run_row["id"]),
            conversation_id=str(run_row["conversation_id"]),
            workflow_key=str(run_row["langgraph_thread_id"]),
            entry_mode=str(run_row["entry_mode"]),
            requested_mode=str(run_row["requested_mode"]),
            status=str(run_row["status"]),
            version=int(run_row["version"]),
            request_text="" if message_row is None else str(message_row["content"]),
            selected_resource_ids=selected_resource_ids,
            selected_resources=selected_resources,
        )


def _selected_resource_ref(value: Row) -> SelectedResourceRef:
    return SelectedResourceRef(
        source=str(value["source"]),
        resource_type=str(value["resource_type"]),
        resource_id=str(value["resource_id"]),
        parent_resource_id=(
            None if value["parent_resource_id"] is None else str(value["parent_resource_id"])
        ),
    )
