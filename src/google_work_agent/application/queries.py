"""Read-side query services for the local FastAPI API."""

from __future__ import annotations

from dataclasses import dataclass
from json import loads
from pathlib import Path
from sqlite3 import Row

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.domain import (
    ActionStatus,
    EffectType,
    RunStatus,
    next_allowed_action_commands,
    next_allowed_run_commands,
)
from google_work_agent.ports import RuntimeStatusProvider, RuntimeSummary, SelectedResourceRef

MAX_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class ConversationListItem:
    id: str
    account_id: str
    title: str
    updated_at_ms: int
    created_at_ms: int


@dataclass(frozen=True, slots=True)
class ConversationPage:
    items: tuple[ConversationListItem, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ActionSnapshot:
    action_id: str
    tool_name: str
    status: str
    version: int
    effect_type: str
    approval_required: bool
    verification_policy: str
    next_allowed_commands: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    run_id: str
    conversation_id: str
    status: str
    version: int
    entry_mode: str
    requested_mode: str
    actual_runtime: str | None
    started_at_ms: int
    finished_at_ms: int | None
    active_plan: dict[str, object] | None
    actions: tuple[ActionSnapshot, ...]
    approvals: tuple[dict[str, object], ...]
    execution_status: dict[str, object]
    verification_summary: dict[str, object]
    recovery_summary: dict[str, object]
    next_allowed_commands: tuple[str, ...]
    snapshot_version: int


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
        runtime_status_provider: RuntimeStatusProvider,
    ) -> None:
        self._database_path = database_path
        self._runtime_status_provider = runtime_status_provider

    def list_conversations(
        self,
        *,
        account_id: str,
        cursor: str | None,
        page_size: int,
    ) -> ConversationPage:
        limit = _validated_page_size(page_size)
        predicate = "WHERE account_id = ?"
        params: list[object] = [account_id]
        if cursor is not None:
            updated_at_ms, conversation_id = _parse_keyset_cursor(cursor)
            predicate += " AND (updated_at_ms < ? OR (updated_at_ms = ? AND id < ?))"
            params.extend([updated_at_ms, updated_at_ms, conversation_id])
        params.append(limit + 1)
        with connect_sqlite(self._database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT id, account_id, title, created_at_ms, updated_at_ms
                FROM conversations
                {predicate}
                ORDER BY updated_at_ms DESC, id DESC
                LIMIT ?;
                """,
                tuple(params),
            ).fetchall()
        items = tuple(_conversation_item_from_row(row) for row in rows[:limit])
        next_cursor = None
        if len(rows) > limit and items:
            last = items[-1]
            next_cursor = f"{last.updated_at_ms}:{last.id}"
        return ConversationPage(items=items, next_cursor=next_cursor)

    def get_conversation(self, conversation_id: str) -> ConversationListItem | None:
        with connect_sqlite(self._database_path) as connection:
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

    def get_run_snapshot(self, run_id: str) -> RunSnapshot | None:
        with connect_sqlite(self._database_path) as connection:
            run_row = connection.execute(
                """
                SELECT id, conversation_id, entry_mode, status, requested_mode,
                       actual_runtime, version, started_at_ms, finished_at_ms
                FROM runs
                WHERE id = ?;
                """,
                (run_id,),
            ).fetchone()
            if run_row is None:
                return None
            plan_row = connection.execute(
                """
                SELECT id, revision_no, status, summary_text, created_at_ms
                FROM plans
                WHERE run_id = ?
                ORDER BY revision_no DESC, id DESC
                LIMIT 1;
                """,
                (run_id,),
            ).fetchone()
            actions: tuple[ActionSnapshot, ...] = ()
            approvals: tuple[dict[str, object], ...] = ()
            verification_summary: dict[str, object] = {
                "verified_count": 0,
                "mismatch_count": 0,
            }
            recovery_count = 0
            if plan_row is not None:
                action_rows = connection.execute(
                    """
                    SELECT id, tool_name, status, version, effect_type,
                           approval_requirement, verification_policy
                    FROM actions
                    WHERE plan_id = ?
                    ORDER BY position ASC, id ASC;
                    """,
                    (str(plan_row["id"]),),
                ).fetchall()
                actions = tuple(_action_snapshot_from_row(row) for row in action_rows)
                recovery_count = sum(
                    1 for action in actions if action.status == ActionStatus.UNKNOWN_RESULT.value
                )
                approvals = tuple(
                    {
                        "approval_id": str(row["id"]),
                        "action_id": str(row["action_id"]),
                        "status": str(row["status"]),
                        "approved_at_ms": int(row["approved_at_ms"]),
                        "expires_at_ms": int(row["expires_at_ms"]),
                    }
                    for row in connection.execute(
                        """
                        SELECT id, action_id, status, approved_at_ms, expires_at_ms
                        FROM approvals
                        WHERE action_id IN (
                            SELECT id FROM actions WHERE plan_id = ?
                        )
                        ORDER BY approved_at_ms DESC, id DESC;
                        """,
                        (str(plan_row["id"]),),
                    ).fetchall()
                )
                verification_rows = connection.execute(
                    """
                    SELECT status, COUNT(*) AS total
                    FROM verifications
                    WHERE execution_attempt_id IN (
                        SELECT id FROM execution_attempts
                        WHERE approval_id IN (
                            SELECT id FROM approvals
                            WHERE action_id IN (SELECT id FROM actions WHERE plan_id = ?)
                        )
                    )
                    GROUP BY status;
                    """,
                    (str(plan_row["id"]),),
                ).fetchall()
                verification_summary = {
                    "verified_count": sum(
                        int(row["total"])
                        for row in verification_rows
                        if str(row["status"]) == "VERIFIED"
                    ),
                    "mismatch_count": sum(
                        int(row["total"])
                        for row in verification_rows
                        if str(row["status"]) == "MISMATCH"
                    ),
                }

        run_status = RunStatus(str(run_row["status"]))
        active_plan = None
        if plan_row is not None:
            active_plan = {
                "plan_id": str(plan_row["id"]),
                "revision_no": int(plan_row["revision_no"]),
                "status": str(plan_row["status"]),
                "summary_text": (
                    None if plan_row["summary_text"] is None else str(plan_row["summary_text"])
                ),
                "created_at_ms": int(plan_row["created_at_ms"]),
            }
        execution_status: dict[str, object] = {
            "action_count": len(actions),
            "terminal_action_count": sum(
                1
                for action in actions
                if action.status
                in {
                    ActionStatus.VERIFIED.value,
                    ActionStatus.REJECTED.value,
                    ActionStatus.FAILED.value,
                    ActionStatus.MISMATCH.value,
                    ActionStatus.BLOCKED.value,
                    ActionStatus.DEPENDENCY_BLOCKED.value,
                }
            ),
        }
        return RunSnapshot(
            run_id=str(run_row["id"]),
            conversation_id=str(run_row["conversation_id"]),
            status=run_status.value,
            version=int(run_row["version"]),
            entry_mode=str(run_row["entry_mode"]),
            requested_mode=str(run_row["requested_mode"]),
            actual_runtime=(
                None if run_row["actual_runtime"] is None else str(run_row["actual_runtime"])
            ),
            started_at_ms=int(run_row["started_at_ms"]),
            finished_at_ms=(
                None if run_row["finished_at_ms"] is None else int(run_row["finished_at_ms"])
            ),
            active_plan=active_plan,
            actions=actions,
            approvals=approvals,
            execution_status=execution_status,
            verification_summary=verification_summary,
            recovery_summary={"unknown_result_action_count": recovery_count},
            next_allowed_commands=tuple(
                item.value for item in next_allowed_run_commands(run_status)
            ),
            snapshot_version=1,
        )

    def get_run_execution_context(self, run_id: str) -> RunExecutionContext | None:
        with connect_sqlite(self._database_path) as connection:
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
            trace_rows = connection.execute(
                """
                SELECT payload_json
                FROM trace_events
                WHERE run_id = ?
                ORDER BY id ASC;
                """,
                (run_id,),
            ).fetchall()
        selected_resource_ids: tuple[str, ...] = ()
        selected_resources: tuple[SelectedResourceRef, ...] = ()
        for row in trace_rows:
            try:
                payload = loads(str(row["payload_json"]))
                attributes = payload.get("attributes", {})
                original = attributes.get("selected_resource_ids", [])
                if isinstance(original, list):
                    selected_resource_ids = tuple(str(item) for item in original)
                selected_original = attributes.get("selected_resources", [])
                if isinstance(selected_original, list):
                    selected_resources = tuple(
                        _selected_resource_ref_from_mapping(item)
                        for item in selected_original
                        if isinstance(item, dict)
                    )
            except Exception:
                continue
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
        with connect_sqlite(self._database_path) as connection:
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
        with connect_sqlite(self._database_path) as connection:
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

    def get_runtime_summary(self) -> RuntimeSummary:
        base = self._runtime_status_provider.get_summary()
        open_runs = self.list_open_runs()
        recovery_required = tuple(
            run.run_id for run in open_runs if run.status == RunStatus.RECOVERY_REQUIRED.value
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
        with connect_sqlite(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT id, email, display_name
                FROM google_accounts
                WHERE disconnected_at_ms IS NULL
                ORDER BY connected_at_ms DESC, id DESC
                LIMIT 1;
                """
            ).fetchone()
        if row is None:
            return None
        return GoogleAccountRecord(
            account_id=str(row["id"]),
            email=str(row["email"]),
            display_name=None if row["display_name"] is None else str(row["display_name"]),
        )


def _validated_page_size(page_size: int) -> int:
    if page_size < 1:
        raise ValueError("page_size must be at least 1")
    if page_size > MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be <= {MAX_PAGE_SIZE}")
    return page_size


def _parse_keyset_cursor(cursor: str) -> tuple[int, str]:
    raw_time, conversation_id = cursor.split(":", 1)
    return int(raw_time), conversation_id


def _selected_resource_ref_from_mapping(value: dict[object, object]) -> SelectedResourceRef:
    return SelectedResourceRef(
        source=str(value["source"]),
        resource_type=str(value["resource_type"]),
        resource_id=str(value["resource_id"]),
        parent_resource_id=(
            None
            if value.get("parent_resource_id") is None
            else str(value["parent_resource_id"])
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


def _action_snapshot_from_row(row: Row) -> ActionSnapshot:
    status = ActionStatus(str(row["status"]))
    effect_type = EffectType(str(row["effect_type"]))
    return ActionSnapshot(
        action_id=str(row["id"]),
        tool_name=str(row["tool_name"]),
        status=status.value,
        version=int(row["version"]),
        effect_type=effect_type.value,
        approval_required=str(row["approval_requirement"]) == "REQUIRED",
        verification_policy=str(row["verification_policy"]),
        next_allowed_commands=tuple(
            item.value for item in next_allowed_action_commands(status, effect_type=effect_type)
        ),
    )
