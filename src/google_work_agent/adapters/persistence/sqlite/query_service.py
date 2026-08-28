"""Read-side query services for the local FastAPI API."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from sqlite3 import Row

from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports import (
    QueryConnectionFactory,
    RuntimeStatusProvider,
    RuntimeSummary,
    SelectedResourceRef,
)


@dataclass(frozen=True, slots=True)
class ConversationListItem:
    id: str
    account_id: str
    title: str
    updated_at_ms: int
    created_at_ms: int


@dataclass(frozen=True, slots=True)
class RunExecutionContext:
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


@dataclass(frozen=True, slots=True)
class OpenRunRecord:
    run_id: str
    workflow_key: str
    status: str
    version: int


@dataclass(frozen=True, slots=True)
class ConversationRunRecord:
    run_id: str
    status: str
    version: int
    started_at_ms: int
    finished_at_ms: int | None = None


@dataclass(frozen=True, slots=True)
class GoogleAccountRecord:
    account_id: str
    email: str
    display_name: str | None


class QueryService:
    """SQLite-backed read model queries for the API layer."""

    def __init__(
        self,
        *,
        database_path: Path,
        connection_factory: QueryConnectionFactory,
        runtime_status_provider: RuntimeStatusProvider,
    ) -> None:
        self._database_path = database_path
        self._connection_factory = connection_factory
        self._runtime_status_provider = runtime_status_provider

    @property
    def database_path(self) -> Path:
        """Database location exposed for canonical read-use-case composition."""

        return self._database_path

    @property
    def connection_factory(self) -> QueryConnectionFactory:
        """Read connection factory exposed without private-field traversal."""

        return self._connection_factory

    def get_conversation(self, conversation_id: str) -> ConversationListItem | None:
        with self._connection_factory(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT id, account_id, title, created_at_ms, updated_at_ms
                FROM conversations
                WHERE id = ?;
                """,
                (conversation_id,),
            ).fetchone()
        if row is None:
            return None
        return _conversation_item_from_row(row)

    def has_cancel_intent(self, run_id: str) -> bool:
        """Return whether an APPLIED RequestCancel receipt durably records intent."""
        with self._connection_factory(self._database_path) as connection:
            rows = connection.execute(
                """
                SELECT command_type, aggregate_type, aggregate_id, status, result_code
                FROM command_receipts
                WHERE command_type = 'RequestRunCancellation'
                  AND aggregate_type = 'Run'
                  AND aggregate_id = ?
                  AND status = 'APPLIED';
                """,
                (run_id,),
            ).fetchall()
        return any(str(row["result_code"]) == "TRANSITION_APPLIED" for row in rows)

    def get_run_execution_context(self, run_id: str) -> RunExecutionContext | None:
        with self._connection_factory(self._database_path) as connection:
            run_row = connection.execute(
                """
                SELECT id, conversation_id, langgraph_thread_id, entry_mode,
                       requested_mode, status, version
                FROM runs
                WHERE id = ?;
                """,
                (run_id,),
            ).fetchone()
            if run_row is None:
                return None
            message_row = connection.execute(
                """
                SELECT content
                FROM messages
                WHERE run_id = ? AND role = 'USER'
                ORDER BY created_at_ms ASC, id ASC
                LIMIT 1;
                """,
                (run_id,),
            ).fetchone()
            resource_rows = connection.execute(
                """
                SELECT source, resource_type, resource_id, parent_resource_id
                FROM resource_refs
                WHERE run_id = ?
                ORDER BY connector_id, resource_type, resource_id;
                """,
                (run_id,),
            ).fetchall()
        selected_resource_ids = tuple(str(row["resource_id"]) for row in resource_rows)
        selected_resources = tuple(
            _selected_resource_ref_from_mapping(row) for row in resource_rows
        )
        return RunExecutionContext(
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

    def list_open_runs(self) -> tuple[OpenRunRecord, ...]:
        with self._connection_factory(self._database_path) as connection:
            rows = connection.execute(
                """
                SELECT id, langgraph_thread_id, status, version
                FROM runs
                WHERE finished_at_ms IS NULL
                ORDER BY started_at_ms ASC, id ASC;
                """
            ).fetchall()
        return tuple(
            OpenRunRecord(
                run_id=str(row["id"]),
                workflow_key=str(row["langgraph_thread_id"]),
                status=str(row["status"]),
                version=int(row["version"]),
            )
            for row in rows
        )

    def get_latest_run_for_conversation(self, conversation_id: str) -> ConversationRunRecord | None:
        with self._connection_factory(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT id, status, version, started_at_ms
                FROM runs
                WHERE conversation_id = ?
                ORDER BY started_at_ms DESC, id DESC
                LIMIT 1;
                """,
                (conversation_id,),
            ).fetchone()
        if row is None:
            return None
        return ConversationRunRecord(
            run_id=str(row["id"]),
            status=str(row["status"]),
            version=int(row["version"]),
            started_at_ms=int(row["started_at_ms"]),
        )

    def list_runs_for_conversation_bounded(
        self, conversation_id: str, *, limit: int
    ) -> tuple[ConversationRunRecord, ...]:
        if limit < 1 or limit > 200:
            raise ValueError("conversation run limit must be between 1 and 200")
        with self._connection_factory(self._database_path) as connection:
            rows = connection.execute(
                """SELECT id, status, version, started_at_ms, finished_at_ms
                   FROM runs
                   WHERE conversation_id=?
                   ORDER BY started_at_ms DESC, id DESC
                   LIMIT ?;""",
                (conversation_id, limit),
            ).fetchall()
        return tuple(
            ConversationRunRecord(
                run_id=str(row["id"]),
                status=str(row["status"]),
                version=int(row["version"]),
                started_at_ms=int(row["started_at_ms"]),
                finished_at_ms=(
                    None if row["finished_at_ms"] is None else int(row["finished_at_ms"])
                ),
            )
            for row in rows
        )

    def get_runtime_summary(self) -> RuntimeSummary:
        base = self._runtime_status_provider.get_summary()
        open_runs = self.list_open_runs()
        recovery_required = tuple(
            run.run_id for run in open_runs if run.status == RunStatusV1.RECOVERY_REQUIRED.value
        )
        return RuntimeSummary(
            google=base.google,
            mcp=base.mcp,
            api_llm=base.api_llm,
            ollama=base.ollama,
            deployment_profile=base.deployment_profile,
            recovery_required_run_ids=recovery_required,
            open_run_ids=tuple(run.run_id for run in open_runs),
            google_connection=base.google_connection,
            mcp_runtime=base.mcp_runtime,
            llm=base.llm,
            safe_mode=base.safe_mode,
            safe_mode_reason_codes=base.safe_mode_reason_codes,
            allowed_operations=base.allowed_operations,
        )

    def get_current_google_account(self) -> GoogleAccountRecord | None:
        with self._connection_factory(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT id, email, display_name
                FROM google_accounts
                WHERE disconnected_at_ms IS NULL
                ORDER BY connected_at_ms DESC, id DESC
                LIMIT 1;
                """,
            ).fetchone()
        if row is None:
            return None
        return GoogleAccountRecord(
            account_id=str(row["id"]),
            email=str(row["email"]),
            display_name=None if row["display_name"] is None else str(row["display_name"]),
        )

    def ensure_google_account_connected(
        self, *, email: str, display_name: str | None, now_ms: int
    ) -> None:
        """Provision or reactivate the `google_accounts` row for one email.

        This is the only writer of `google_accounts`: it runs whenever the
        API observes a resolved, connected account (see
        GetGoogleConnectionService), keyed by email so a reconnect with the
        same Google account reuses its existing id rather than orphaning
        conversations that reference it as a foreign key.
        """

        account_id = _google_account_id_for_email(email)
        with self._connection_factory(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO google_accounts
                    (id, email, display_name, connected_at_ms, disconnected_at_ms)
                VALUES (:id, :email, :display_name, :now_ms, NULL)
                ON CONFLICT(email) DO UPDATE SET
                    display_name = excluded.display_name,
                    disconnected_at_ms = NULL;
                """,
                {
                    "id": account_id,
                    "email": email,
                    "display_name": display_name,
                    "now_ms": now_ms,
                },
            )


def _google_account_id_for_email(email: str) -> str:
    """Deterministic id so re-provisioning the same email is naturally idempotent."""

    digest = sha256(email.strip().lower().encode("utf-8")).hexdigest()
    return f"acct-{digest[:24]}"


def _selected_resource_ref_from_mapping(value: Row) -> SelectedResourceRef:
    return SelectedResourceRef(
        source=str(value["source"]),
        resource_type=str(value["resource_type"]),
        resource_id=str(value["resource_id"]),
        parent_resource_id=(
            None if value["parent_resource_id"] is None else str(value["parent_resource_id"])
        ),
    )


def _conversation_item_from_row(row: Row) -> ConversationListItem:
    return ConversationListItem(
        id=str(row["id"]),
        account_id=str(row["account_id"]),
        title=str(row["title"]),
        created_at_ms=int(row["created_at_ms"]),
        updated_at_ms=int(row["updated_at_ms"]),
    )
