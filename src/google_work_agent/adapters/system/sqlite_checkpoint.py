"""SQLite authority for LangGraph checkpoints and their typed projection."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from threading import Lock
from typing import Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver, get_checkpoint_metadata
from langgraph.checkpoint.sqlite import SqliteSaver

from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.system.contracts.checkpoint import (
    GraphCheckpointEnvelopeV1,
    RetrievalCacheRequirementV1,
)
from google_work_agent.ports.system.contracts.external_llm_transfer_scope import (
    ExternalLlmTransferScopeV1,
)
from google_work_agent.ports.system.contracts.retrieval_head import RetrievalHeadV1
from google_work_agent.ports.system.contracts.workflow_binding import (
    GraphProfileIdV1,
    WorkflowBindingV1,
)
from google_work_agent.ports.system.contracts.workflow_handoff import (
    AgentNodeResumeTargetV2,
    CompiledAgentSubgraphIdV1,
    MainControlResumeTargetV2,
    MainResumeStageIdV1,
    RegisteredResumeTargetRefV2,
    SemanticAgentOwnerIdV1,
    WorkflowExecutionAdmissionV1,
)


class CheckpointConflictError(RuntimeError):
    """Typed metadata does not identify the exact native checkpoint."""


@dataclass(frozen=True, slots=True)
class _WriteContext:
    admission: WorkflowExecutionAdmissionV1
    applied_handoff_id: str | None
    owner_scope: str
    resume_target: RegisteredResumeTargetRefV2
    retrieval_requirements: tuple[RetrievalCacheRequirementV1, ...]
    pre_reauth_status: RunStatusV1 | None


_WRITE_CONTEXT: ContextVar[_WriteContext | None] = ContextVar(
    "workflow_checkpoint_write_context", default=None
)


class SqliteCheckpointAdapter(BaseCheckpointSaver[Any]):
    """Own native LangGraph rows and the joined canonical metadata projection."""

    def __init__(
        self,
        database_path: Path,
        *,
        now_ms: Callable[[], int],
        target_resolver: Callable[
            [
                Mapping[str, object],
                GraphProfileIdV1,
                str,
                RegisteredResumeTargetRefV2,
            ],
            RegisteredResumeTargetRefV2,
        ]
        | None = None,
    ) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        self._initialize(
            connection=connection,
            now_ms=now_ms,
            owns_connection=True,
            target_resolver=target_resolver,
        )
        self._database_path: Path | None = database_path
        self._delegate.setup()
        self._setup_checkpoint_storage(commit=True)

    def _initialize(
        self,
        *,
        connection: sqlite3.Connection,
        now_ms: Callable[[], int],
        owns_connection: bool,
        target_resolver: Callable[
            [
                Mapping[str, object],
                GraphProfileIdV1,
                str,
                RegisteredResumeTargetRefV2,
            ],
            RegisteredResumeTargetRefV2,
        ]
        | None,
    ) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row
        self._delegate = SqliteSaver(self._connection)
        super().__init__(serde=self._delegate.serde)
        self._now_ms = now_ms
        self._owns_connection = owns_connection
        self._target_resolver = target_resolver
        self._is_closed = False
        self._database_path = None
        self._projection_update_lock = Lock()
        self._projection_updates: dict[tuple[str, str], GraphCheckpointEnvelopeV1] = {}
        self._active_context_lock = Lock()
        self._active_contexts: dict[tuple[str, str], _WriteContext] = {}

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        if self._database_path is None:
            yield self._connection
            return
        connection = sqlite3.connect(self._database_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def _setup_checkpoint_storage(self, *, commit: bool) -> None:
        with self._delegate.lock:
            self._connection.execute("PRAGMA foreign_keys = ON;")
            self._setup_workflow_binding_storage()
            self._connection.execute(
                """CREATE TABLE IF NOT EXISTS workflow_checkpoint_envelopes (
                    langgraph_thread_id TEXT NOT NULL,
                    checkpoint_ns TEXT NOT NULL DEFAULT '',
                    checkpoint_id TEXT NOT NULL,
                    checkpoint_generation INTEGER NOT NULL CHECK (checkpoint_generation >= 1),
                    run_id TEXT NOT NULL,
                    graph_profile TEXT NOT NULL,
                    graph_version TEXT NOT NULL,
                    owner_scope TEXT NOT NULL,
                    registered_resume_target_json TEXT,
                    applied_handoff_id TEXT,
                    execution_admission_id TEXT,
                    active_handoff_id TEXT,
                    active_handoff_run_sequence INTEGER,
                    retrieval_cache_requirements_json TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    pre_reauth_status TEXT,
                    PRIMARY KEY (langgraph_thread_id, checkpoint_ns, checkpoint_id),
                    UNIQUE (run_id, langgraph_thread_id, checkpoint_generation),
                    FOREIGN KEY (langgraph_thread_id, checkpoint_ns, checkpoint_id)
                        REFERENCES checkpoints(thread_id, checkpoint_ns, checkpoint_id)
                        ON DELETE CASCADE
                );"""
            )
            columns = {
                str(row[1])
                for row in self._connection.execute(
                    "PRAGMA table_info(workflow_checkpoint_envelopes);"
                ).fetchall()
            }
            if "pre_reauth_status" not in columns:
                self._connection.execute(
                    "ALTER TABLE workflow_checkpoint_envelopes ADD COLUMN pre_reauth_status TEXT;"
                )
            self._connection.execute(
                """CREATE INDEX IF NOT EXISTS ix_workflow_checkpoint_latest
                ON workflow_checkpoint_envelopes(
                    run_id, langgraph_thread_id, checkpoint_generation DESC
                );"""
            )
            self._setup_retrieval_head_storage()
            self._setup_external_llm_scope_storage()
            if commit:
                self._connection.commit()

    def _setup_workflow_binding_storage(self) -> None:
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS workflow_bindings (
                workflow_key TEXT PRIMARY KEY,
                run_id TEXT NOT NULL UNIQUE,
                langgraph_thread_id TEXT NOT NULL UNIQUE,
                graph_profile TEXT NOT NULL,
                graph_version TEXT NOT NULL,
                requested_mode TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
            );"""
        )

    def _setup_retrieval_head_storage(self) -> None:
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS workflow_retrieval_heads (
                run_id TEXT PRIMARY KEY,
                langgraph_thread_id TEXT NOT NULL,
                retrieval_revision INTEGER NOT NULL CHECK (retrieval_revision >= 1),
                retrieval_artifact_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                checkpoint_generation INTEGER NOT NULL CHECK (checkpoint_generation >= 1),
                FOREIGN KEY (langgraph_thread_id, checkpoint_ns, checkpoint_id)
                    REFERENCES workflow_checkpoint_envelopes(
                        langgraph_thread_id, checkpoint_ns, checkpoint_id
                    ) ON DELETE CASCADE
            );"""
        )

    def _setup_external_llm_scope_storage(self) -> None:
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS workflow_external_llm_scopes (
                run_id TEXT PRIMARY KEY,
                scope_revision INTEGER NOT NULL CHECK (scope_revision >= 1),
                scope_hash TEXT NOT NULL,
                source_kinds_json TEXT NOT NULL,
                data_classes_json TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
            );"""
        )

    def create_workflow_binding(self, binding: WorkflowBindingV1) -> None:
        existing = self.load_workflow_binding(binding.run_id)
        if existing is not None:
            if existing != binding:
                raise CheckpointConflictError("Run already has a different workflow binding")
            return
        self._connection.execute(
            """INSERT INTO workflow_bindings (
                workflow_key, run_id, langgraph_thread_id, graph_profile,
                graph_version, requested_mode, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?);""",
            (
                binding.workflow_key,
                binding.run_id,
                binding.langgraph_thread_id,
                binding.graph_profile,
                binding.graph_version,
                binding.requested_mode,
                binding.created_at_ms,
            ),
        )

    def load_workflow_binding(self, run_id: str) -> WorkflowBindingV1 | None:
        with self._read_connection() as connection:
            row = connection.execute(
                """SELECT workflow_key, run_id, langgraph_thread_id, graph_profile,
                          graph_version, requested_mode, created_at_ms
                   FROM workflow_bindings WHERE run_id=?;""",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return WorkflowBindingV1(
            schema_version=1,
            workflow_key=str(row["workflow_key"]),
            run_id=str(row["run_id"]),
            langgraph_thread_id=str(row["langgraph_thread_id"]),
            graph_profile=cast(GraphProfileIdV1, str(row["graph_profile"])),
            graph_version=str(row["graph_version"]),
            requested_mode=cast(Any, str(row["requested_mode"])),
            created_at_ms=int(row["created_at_ms"]),
        )

    @property
    def config_specs(self) -> list[Any]:
        return list(self._delegate.config_specs)

    @contextmanager
    def execution_scope(
        self,
        admission: WorkflowExecutionAdmissionV1,
        *,
        applied_handoff_id: str | None,
        owner_scope: str,
        resume_target: RegisteredResumeTargetRefV2,
    ) -> Iterator[None]:
        latest = self.load_same_run_checkpoint(
            admission.effective_binding.run_id,
            admission.effective_binding.langgraph_thread_id,
        )
        context = _WriteContext(
            admission=admission,
            applied_handoff_id=applied_handoff_id,
            owner_scope=owner_scope,
            resume_target=resume_target,
            retrieval_requirements=() if latest is None else latest.retrieval_cache_requirements,
            pre_reauth_status=None if latest is None else latest.pre_reauth_status,
        )
        key = (
            admission.effective_binding.run_id,
            admission.effective_binding.langgraph_thread_id,
        )
        with self._projection_update_lock:
            self._projection_updates.pop(key, None)
        with self._active_context_lock:
            self._active_contexts[key] = context
        token = _WRITE_CONTEXT.set(context)
        try:
            yield
        finally:
            _WRITE_CONTEXT.reset(token)
            final_context = context
            with self._active_context_lock:
                active = self._active_contexts.get(key)
                if (
                    active is not None
                    and active.admission.admission_id == context.admission.admission_id
                ):
                    final_context = active
                    self._active_contexts.pop(key, None)
            with self._projection_update_lock:
                pending_update = self._projection_updates.get(key)
            latest = self.load_same_run_checkpoint(*key)
            if latest is not None and (
                pending_update is not None
                or latest.retrieval_cache_requirements
                != final_context.retrieval_requirements
            ):
                self.store_same_run_checkpoint(
                    replace(
                        latest,
                        owner_scope=(
                            latest.owner_scope
                            if pending_update is None
                            else pending_update.owner_scope
                        ),
                        registered_resume_target=(
                            latest.registered_resume_target
                            if pending_update is None
                            else pending_update.registered_resume_target
                        ),
                        retrieval_cache_requirements=final_context.retrieval_requirements,
                        pre_reauth_status=(
                            latest.pre_reauth_status
                            if pending_update is None
                            else pending_update.pre_reauth_status
                        ),
                        created_at_ms=(
                            latest.created_at_ms
                            if pending_update is None
                            else pending_update.created_at_ms
                        ),
                    )
                )

    def get_tuple(self, config: Any) -> Any:
        return self._delegate.get_tuple(config)

    def list(
        self,
        config: Any | None,
        *,
        filter: dict[str, Any] | None = None,
        before: Any = None,
        limit: int | None = None,
    ) -> Iterator[Any]:
        return self._delegate.list(config, filter=filter, before=before, limit=limit)

    def put(self, config: Any, checkpoint: Any, metadata: Any, new_versions: Any) -> Any:
        configurable = config["configurable"]
        thread_id = str(configurable["thread_id"])
        checkpoint_ns = str(configurable.get("checkpoint_ns", ""))
        checkpoint_id = str(checkpoint["id"])
        checkpoint_type, checkpoint_blob = self.serde.dumps_typed(checkpoint)
        metadata_blob = json.dumps(
            get_checkpoint_metadata(config, metadata), ensure_ascii=False
        ).encode("utf-8", "ignore")
        context = _WRITE_CONTEXT.get()
        with self._active_context_lock:
            active_context = next(
                (
                    active
                    for (_run_id, active_thread_id), active in self._active_contexts.items()
                    if active_thread_id == thread_id
                ),
                None,
            )
        if context is None or (
            active_context is not None
            and active_context.admission.admission_id == context.admission.admission_id
            and active_context.retrieval_requirements != context.retrieval_requirements
        ):
            context = active_context
        observed_requirements = _retrieval_requirements_from_checkpoint(checkpoint)
        if context is not None and observed_requirements is not None:
            context = replace(context, retrieval_requirements=observed_requirements)
            binding = context.admission.effective_binding
            active_key = (binding.run_id, binding.langgraph_thread_id)
            with self._active_context_lock:
                self._active_contexts[active_key] = context
            _WRITE_CONTEXT.set(context)
        pending_update = None
        pending_key = None
        if context is not None:
            binding = context.admission.effective_binding
            pending_key = (binding.run_id, binding.langgraph_thread_id)
            with self._projection_update_lock:
                pending_update = self._projection_updates.get(pending_key)
            if pending_update is not None:
                context = replace(
                    context,
                    owner_scope=pending_update.owner_scope,
                    resume_target=pending_update.registered_resume_target or context.resume_target,
                    pre_reauth_status=pending_update.pre_reauth_status,
                )
        with self._delegate.lock:
            cursor = self._connection.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE;")
                cursor.execute(
                    """INSERT OR REPLACE INTO checkpoints (
                        thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
                        type, checkpoint, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?);""",
                    (
                        thread_id,
                        checkpoint_ns,
                        checkpoint_id,
                        configurable.get("checkpoint_id"),
                        checkpoint_type,
                        checkpoint_blob,
                        metadata_blob,
                    ),
                )
                if context is not None:
                    self._insert_projection(
                        cursor,
                        context=context,
                        projection_override=pending_update,
                        checkpoint=checkpoint,
                        checkpoint_ns=checkpoint_ns,
                        checkpoint_id=checkpoint_id,
                    )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
            finally:
                cursor.close()
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    def put_writes(
        self,
        config: Any,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        self._delegate.put_writes(config, writes, task_id, task_path)

    def delete_thread(self, thread_id: str) -> None:
        self._delegate.delete_thread(thread_id)

    def get_next_version(self, current: Any, channel: Any) -> Any:
        return self._delegate.get_next_version(current, channel)

    def get_delta_channel_history(self, *, config: Any, channels: Sequence[str]) -> Any:
        return self._delegate.get_delta_channel_history(config=config, channels=channels)

    def store_same_run_checkpoint(self, checkpoint: GraphCheckpointEnvelopeV1) -> None:
        """Update evidence on an existing native checkpoint; never create a second blob."""
        context = _WRITE_CONTEXT.get()
        if context is None:
            with self._active_context_lock:
                context = self._active_contexts.get(
                    (checkpoint.run_id, checkpoint.langgraph_thread_id)
                )
        if (
            context is not None
            and context.admission.effective_binding.run_id == checkpoint.run_id
            and checkpoint.registered_resume_target is not None
        ):
            # A LangGraph node runs while the native saver lock is held. Stage the
            # typed projection in the execution context; the saver persists it with
            # the native checkpoint produced after the node returns.
            _WRITE_CONTEXT.set(
                replace(
                    context,
                    owner_scope=checkpoint.owner_scope,
                    resume_target=checkpoint.registered_resume_target,
                    pre_reauth_status=checkpoint.pre_reauth_status,
                )
            )
            with self._projection_update_lock:
                self._projection_updates[(checkpoint.run_id, checkpoint.langgraph_thread_id)] = (
                    checkpoint
                )
            return
        with self._delegate.lock:
            cursor = self._connection.cursor()
            owns_transaction = not self._connection.in_transaction
            try:
                row = cursor.execute(
                    """SELECT e.checkpoint_generation, e.run_id, c.checkpoint
                    FROM workflow_checkpoint_envelopes e JOIN checkpoints c
                      ON c.thread_id=e.langgraph_thread_id
                     AND c.checkpoint_ns=e.checkpoint_ns
                     AND c.checkpoint_id=e.checkpoint_id
                    WHERE e.langgraph_thread_id=? AND e.checkpoint_id=?;""",
                    (checkpoint.langgraph_thread_id, checkpoint.checkpoint_id),
                ).fetchone()
                if (
                    row is None
                    or int(row["checkpoint_generation"]) != checkpoint.checkpoint_generation
                    or str(row["run_id"]) != checkpoint.run_id
                    or bytes(row["checkpoint"]) != checkpoint.checkpoint_blob
                ):
                    raise CheckpointConflictError(
                        "typed metadata must reference the exact native checkpoint"
                    )
                if owns_transaction:
                    cursor.execute("BEGIN IMMEDIATE;")
                cursor.execute(
                    """UPDATE workflow_checkpoint_envelopes SET
                        owner_scope=?, registered_resume_target_json=?,
                        applied_handoff_id=?, execution_admission_id=?,
                        active_handoff_id=?, active_handoff_run_sequence=?,
                        retrieval_cache_requirements_json=?, created_at_ms=?,
                        pre_reauth_status=?
                    WHERE langgraph_thread_id=? AND checkpoint_id=?;""",
                    (
                        checkpoint.owner_scope,
                        _json_or_none(checkpoint.registered_resume_target),
                        checkpoint.applied_handoff_id,
                        checkpoint.execution_admission_id,
                        checkpoint.active_handoff_id,
                        checkpoint.active_handoff_run_sequence,
                        _requirements_json(checkpoint.retrieval_cache_requirements),
                        checkpoint.created_at_ms,
                        None
                        if checkpoint.pre_reauth_status is None
                        else checkpoint.pre_reauth_status.value,
                        checkpoint.langgraph_thread_id,
                        checkpoint.checkpoint_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise CheckpointConflictError("typed checkpoint projection is missing")
                if (
                    context is not None
                    and context.admission.effective_binding.run_id == checkpoint.run_id
                    and checkpoint.registered_resume_target is not None
                ):
                    _WRITE_CONTEXT.set(
                        replace(
                            context,
                            owner_scope=checkpoint.owner_scope,
                            resume_target=checkpoint.registered_resume_target,
                            pre_reauth_status=checkpoint.pre_reauth_status,
                        )
                    )
                if owns_transaction:
                    self._connection.commit()
            except Exception:
                if owns_transaction:
                    self._connection.rollback()
                raise
            finally:
                cursor.close()

    def load_same_run_checkpoint(
        self, run_id: str, thread_id: str
    ) -> GraphCheckpointEnvelopeV1 | None:
        with self._read_connection() as connection:
            row = connection.execute(
                """SELECT e.*, c.checkpoint AS checkpoint_blob
                FROM workflow_checkpoint_envelopes e JOIN checkpoints c
                  ON c.thread_id=e.langgraph_thread_id
                 AND c.checkpoint_ns=e.checkpoint_ns
                 AND c.checkpoint_id=e.checkpoint_id
                WHERE e.run_id=? AND e.langgraph_thread_id=?
                  AND e.checkpoint_ns=''
                ORDER BY e.checkpoint_generation DESC LIMIT 1;""",
                (run_id, thread_id),
            ).fetchone()
        if row is None:
            return None
        checkpoint = _to_checkpoint(row)
        with self._projection_update_lock:
            pending_update = self._projection_updates.get((run_id, thread_id))
        if pending_update is None:
            return checkpoint
        return replace(
            checkpoint,
            owner_scope=pending_update.owner_scope,
            registered_resume_target=pending_update.registered_resume_target,
            pre_reauth_status=pending_update.pre_reauth_status,
            created_at_ms=pending_update.created_at_ms,
        )

    def store_retrieval_head(self, head: RetrievalHeadV1) -> None:
        """Store metadata only when it names an existing native checkpoint."""
        with self._delegate.lock:
            cursor = self._connection.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE;")
                self._store_retrieval_head(cursor, head=head, checkpoint_ns="")
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
            finally:
                cursor.close()

    def load_retrieval_head(self, run_id: str) -> RetrievalHeadV1 | None:
        with self._read_connection() as connection:
            row = connection.execute(
                """SELECT run_id, langgraph_thread_id, retrieval_revision,
                          retrieval_artifact_id, checkpoint_id, checkpoint_generation
                   FROM workflow_retrieval_heads WHERE run_id=?;""",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return RetrievalHeadV1(
            schema_version=1,
            run_id=str(row["run_id"]),
            langgraph_thread_id=str(row["langgraph_thread_id"]),
            retrieval_revision=int(row["retrieval_revision"]),
            retrieval_artifact_id=str(row["retrieval_artifact_id"]),
            checkpoint_id=str(row["checkpoint_id"]),
            checkpoint_generation=int(row["checkpoint_generation"]),
        )

    def store_external_llm_scope(self, scope: ExternalLlmTransferScopeV1) -> None:
        existing = self.load_external_llm_scope(scope.run_id)
        if existing is not None and scope.scope_revision < existing.scope_revision:
            raise CheckpointConflictError("external LLM scope revision regressed")
        if (
            existing is not None
            and scope.scope_revision == existing.scope_revision
            and scope != existing
        ):
            raise CheckpointConflictError("external LLM scope revision conflicts")
        with self._delegate.lock:
            self._connection.execute(
                """INSERT INTO workflow_external_llm_scopes (
                    run_id, scope_revision, scope_hash, source_kinds_json, data_classes_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    scope_revision=excluded.scope_revision,
                    scope_hash=excluded.scope_hash,
                    source_kinds_json=excluded.source_kinds_json,
                    data_classes_json=excluded.data_classes_json;""",
                (
                    scope.run_id,
                    scope.scope_revision,
                    scope.scope_hash,
                    json.dumps(list(scope.source_kinds), sort_keys=True),
                    json.dumps(list(scope.data_classes), sort_keys=True),
                ),
            )
            if self._owns_connection:
                self._connection.commit()

    def load_external_llm_scope(self, run_id: str) -> ExternalLlmTransferScopeV1 | None:
        with self._read_connection() as connection:
            row = connection.execute(
                """SELECT run_id, scope_revision, scope_hash,
                          source_kinds_json, data_classes_json
                   FROM workflow_external_llm_scopes WHERE run_id=?;""",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return ExternalLlmTransferScopeV1(
            schema_version=1,
            run_id=str(row["run_id"]),
            scope_revision=int(row["scope_revision"]),
            scope_hash=str(row["scope_hash"]),
            source_kinds=list(json.loads(str(row["source_kinds_json"]))),
            data_classes=list(json.loads(str(row["data_classes_json"]))),
        )

    def release_active_lineage(
        self, *, run_id: str, thread_id: str, handoff_id: str, run_sequence: int
    ) -> None:
        latest = self.load_same_run_checkpoint(run_id, thread_id)
        if (
            latest is not None
            and latest.active_handoff_id == handoff_id
            and latest.active_handoff_run_sequence == run_sequence
        ):
            self.store_same_run_checkpoint(
                replace(
                    latest,
                    execution_admission_id=None,
                    active_handoff_id=None,
                    active_handoff_run_sequence=None,
                )
            )

    def flush(self) -> None:
        with self._delegate.lock:
            self._connection.commit()

    def delete_run_checkpoints(self, run_id: str) -> None:
        with self._delegate.lock:
            cursor = self._connection.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE;")
                rows = cursor.execute(
                    """SELECT langgraph_thread_id, checkpoint_ns, checkpoint_id
                    FROM workflow_checkpoint_envelopes WHERE run_id=?;""",
                    (run_id,),
                ).fetchall()
                for row in rows:
                    cursor.execute(
                        """DELETE FROM checkpoints
                        WHERE thread_id=? AND checkpoint_ns=? AND checkpoint_id=?;""",
                        tuple(row),
                    )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
            finally:
                cursor.close()

    def close(self) -> None:
        if self._is_closed or not self._owns_connection:
            return
        with self._delegate.lock:
            if not self._is_closed:
                self._connection.close()
                self._is_closed = True

    def _insert_projection(
        self,
        cursor: sqlite3.Cursor,
        *,
        context: _WriteContext,
        projection_override: GraphCheckpointEnvelopeV1 | None,
        checkpoint: Mapping[str, Any],
        checkpoint_ns: str,
        checkpoint_id: str,
    ) -> None:
        admission = context.admission
        binding = admission.effective_binding
        prior = cursor.execute(
            """SELECT checkpoint_generation, owner_scope,
                      registered_resume_target_json, execution_admission_id,
                      active_handoff_id, active_handoff_run_sequence
               FROM workflow_checkpoint_envelopes
               WHERE run_id=? AND langgraph_thread_id=?
               ORDER BY checkpoint_generation DESC LIMIT 1;""",
            (binding.run_id, binding.langgraph_thread_id),
        ).fetchone()
        generation = 1 if prior is None else int(prior["checkpoint_generation"]) + 1
        inherited_target = (
            None if prior is None else _resume_target(prior["registered_resume_target_json"])
        )
        inherits_active_lineage = (
            prior is not None
            and str(prior["execution_admission_id"]) == admission.admission_id
            and str(prior["active_handoff_id"]) == admission.handoff_id
            and int(prior["active_handoff_run_sequence"]) == admission.handoff_run_sequence
            and inherited_target is not None
        )
        fallback = (
            cast(RegisteredResumeTargetRefV2, inherited_target)
            if inherits_active_lineage
            else context.resume_target
        )
        target = (
            projection_override.registered_resume_target
            if projection_override is not None
            and projection_override.registered_resume_target is not None
            else (
                fallback
                if self._target_resolver is None
                else self._target_resolver(
                    checkpoint,
                    binding.graph_profile,
                    binding.graph_version,
                    fallback,
                )
            )
        )
        owner_scope: str
        if projection_override is not None:
            owner_scope = projection_override.owner_scope
        elif isinstance(target, AgentNodeResumeTargetV2):
            owner_scope = target.semantic_owner_id
        elif inherits_active_lineage:
            owner_scope = str(prior["owner_scope"])
        else:
            owner_scope = context.owner_scope
        cursor.execute(
            """INSERT INTO workflow_checkpoint_envelopes (
                langgraph_thread_id, checkpoint_ns, checkpoint_id,
                checkpoint_generation, run_id, graph_profile, graph_version,
                owner_scope, registered_resume_target_json, applied_handoff_id,
                execution_admission_id, active_handoff_id,
                active_handoff_run_sequence, retrieval_cache_requirements_json,
                created_at_ms, pre_reauth_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);""",
            (
                binding.langgraph_thread_id,
                checkpoint_ns,
                checkpoint_id,
                generation,
                binding.run_id,
                binding.graph_profile,
                binding.graph_version,
                owner_scope,
                _json_or_none(target),
                context.applied_handoff_id,
                admission.admission_id,
                admission.handoff_id,
                admission.handoff_run_sequence,
                _requirements_json(context.retrieval_requirements),
                self._now_ms(),
                None if context.pre_reauth_status is None else context.pre_reauth_status.value,
            ),
        )
        head = _retrieval_head_from_checkpoint(
            checkpoint,
            run_id=binding.run_id,
            thread_id=binding.langgraph_thread_id,
            checkpoint_id=checkpoint_id,
            checkpoint_generation=generation,
        )
        if head is not None:
            self._store_retrieval_head(cursor, head=head, checkpoint_ns=checkpoint_ns)

    def _store_retrieval_head(
        self,
        cursor: sqlite3.Cursor,
        *,
        head: RetrievalHeadV1,
        checkpoint_ns: str,
    ) -> None:
        checkpoint = cursor.execute(
            """SELECT run_id, checkpoint_generation
               FROM workflow_checkpoint_envelopes
               WHERE langgraph_thread_id=? AND checkpoint_ns=? AND checkpoint_id=?;""",
            (head.langgraph_thread_id, checkpoint_ns, head.checkpoint_id),
        ).fetchone()
        if (
            checkpoint is None
            or str(checkpoint["run_id"]) != head.run_id
            or int(checkpoint["checkpoint_generation"]) != head.checkpoint_generation
        ):
            raise CheckpointConflictError(
                "retrieval head must reference the exact native checkpoint"
            )
        existing = cursor.execute(
            """SELECT retrieval_revision, retrieval_artifact_id,
                      checkpoint_id, checkpoint_generation
               FROM workflow_retrieval_heads WHERE run_id=?;""",
            (head.run_id,),
        ).fetchone()
        if existing is not None:
            current_revision = int(existing["retrieval_revision"])
            if head.retrieval_revision < current_revision:
                raise CheckpointConflictError("retrieval head revision cannot move backward")
            if head.retrieval_revision == current_revision:
                if str(existing["retrieval_artifact_id"]) != head.retrieval_artifact_id:
                    raise CheckpointConflictError(
                        "retrieval revision identifies a different artifact"
                    )
                current_generation = int(existing["checkpoint_generation"])
                if head.checkpoint_generation < current_generation:
                    raise CheckpointConflictError("retrieval head checkpoint cannot move backward")
                if (
                    head.checkpoint_generation == current_generation
                    and str(existing["checkpoint_id"]) == head.checkpoint_id
                ):
                    return
        cursor.execute(
            """INSERT INTO workflow_retrieval_heads (
                   run_id, langgraph_thread_id, retrieval_revision,
                   retrieval_artifact_id, checkpoint_ns, checkpoint_id,
                   checkpoint_generation
               ) VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(run_id) DO UPDATE SET
                   langgraph_thread_id=excluded.langgraph_thread_id,
                   retrieval_revision=excluded.retrieval_revision,
                   retrieval_artifact_id=excluded.retrieval_artifact_id,
                   checkpoint_ns=excluded.checkpoint_ns,
                   checkpoint_id=excluded.checkpoint_id,
                   checkpoint_generation=excluded.checkpoint_generation;""",
            (
                head.run_id,
                head.langgraph_thread_id,
                head.retrieval_revision,
                head.retrieval_artifact_id,
                checkpoint_ns,
                head.checkpoint_id,
                head.checkpoint_generation,
            ),
        )


def _retrieval_head_from_checkpoint(
    checkpoint: Mapping[str, Any],
    *,
    run_id: str,
    thread_id: str,
    checkpoint_id: str,
    checkpoint_generation: int,
) -> RetrievalHeadV1 | None:
    channels = checkpoint.get("channel_values")
    if not isinstance(channels, Mapping):
        return None
    retrieval_result = channels.get("retrieval_result")
    if not isinstance(retrieval_result, Mapping):
        return None
    meta = retrieval_result.get("meta")
    if not isinstance(meta, Mapping):
        return None
    artifact_id = meta.get("artifact_id")
    revision = meta.get("revision")
    if not isinstance(artifact_id, str) or not artifact_id:
        return None
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        return None
    return RetrievalHeadV1(
        schema_version=1,
        run_id=run_id,
        langgraph_thread_id=thread_id,
        retrieval_revision=revision,
        retrieval_artifact_id=artifact_id,
        checkpoint_id=checkpoint_id,
        checkpoint_generation=checkpoint_generation,
    )


def _retrieval_requirements_from_checkpoint(
    checkpoint: Mapping[str, Any],
) -> tuple[RetrievalCacheRequirementV1, ...] | None:
    """Project bounded cache identities from Retrieval-local channels only."""

    channels = checkpoint.get("channel_values")
    if not isinstance(channels, Mapping):
        return None
    handles = channels.get("__context_read_result_handles__")
    bindings = channels.get("__context_read_bindings__")
    if not isinstance(handles, list) or not isinstance(bindings, Mapping):
        # Once Retrieval has produced its durable parent result, memory-only
        # local read handles are no longer a resume prerequisite.
        return () if isinstance(channels.get("retrieval_result"), Mapping) else None
    requirements: list[RetrievalCacheRequirementV1] = []
    seen: set[str] = set()
    for handle in handles:
        if not isinstance(handle, str) or not handle or handle in seen:
            continue
        binding = bindings.get(handle)
        if not isinstance(binding, Mapping):
            raise CheckpointConflictError("Retrieval cache handle is missing its typed binding")
        route_id = binding.get("route_id")
        query_hash = binding.get("query_identity_hash")
        if (
            not isinstance(route_id, str)
            or not route_id
            or not isinstance(query_hash, str)
            or not query_hash
        ):
            raise CheckpointConflictError("Retrieval cache binding is malformed")
        seen.add(handle)
        requirements.append(
            RetrievalCacheRequirementV1(
                schema_version=1,
                read_result_handle=handle,
                route_id=route_id,
                query_identity_hash=query_hash,
            )
        )
    return tuple(requirements)


def _requirements_json(requirements: tuple[RetrievalCacheRequirementV1, ...]) -> str:
    return json.dumps(
        [asdict(item) for item in requirements], sort_keys=True, separators=(",", ":")
    )


def _to_checkpoint(row: sqlite3.Row) -> GraphCheckpointEnvelopeV1:
    requirements = cast(
        list[dict[str, object]], json.loads(str(row["retrieval_cache_requirements_json"]))
    )
    return GraphCheckpointEnvelopeV1(
        schema_version=1,
        checkpoint_id=str(row["checkpoint_id"]),
        checkpoint_generation=int(row["checkpoint_generation"]),
        run_id=str(row["run_id"]),
        langgraph_thread_id=str(row["langgraph_thread_id"]),
        graph_profile=cast(GraphProfileIdV1, str(row["graph_profile"])),
        graph_version=str(row["graph_version"]),
        owner_scope=str(row["owner_scope"]),
        registered_resume_target=_resume_target(row["registered_resume_target_json"]),
        applied_handoff_id=_optional_text(row["applied_handoff_id"]),
        execution_admission_id=_optional_text(row["execution_admission_id"]),
        active_handoff_id=_optional_text(row["active_handoff_id"]),
        active_handoff_run_sequence=None
        if row["active_handoff_run_sequence"] is None
        else int(row["active_handoff_run_sequence"]),
        retrieval_cache_requirements=tuple(
            RetrievalCacheRequirementV1(
                schema_version=1,
                read_result_handle=str(item["read_result_handle"]),
                route_id=str(item["route_id"]),
                query_identity_hash=str(item["query_identity_hash"]),
            )
            for item in requirements
        ),
        created_at_ms=int(row["created_at_ms"]),
        checkpoint_blob=bytes(row["checkpoint_blob"]),
        pre_reauth_status=(
            None if row["pre_reauth_status"] is None else RunStatusV1(str(row["pre_reauth_status"]))
        ),
    )


def _resume_target(value: object | None) -> RegisteredResumeTargetRefV2 | None:
    if value is None:
        return None
    item = cast(dict[str, object], json.loads(str(value)))
    profile = cast(GraphProfileIdV1, str(item["graph_profile"]))
    if item["kind"] == "AGENT_NODE":
        return AgentNodeResumeTargetV2(
            kind="AGENT_NODE",
            semantic_owner_id=cast(SemanticAgentOwnerIdV1, str(item["semantic_owner_id"])),
            compiled_subgraph_id=cast(CompiledAgentSubgraphIdV1, str(item["compiled_subgraph_id"])),
            node_id=str(item["node_id"]),
            graph_profile=profile,
            graph_version=str(item["graph_version"]),
        )
    return MainControlResumeTargetV2(
        kind="MAIN_CONTROL",
        stage_id=cast(MainResumeStageIdV1, str(item["stage_id"])),
        graph_profile=profile,
        graph_version=str(item["graph_version"]),
    )


def _json_or_none(value: RegisteredResumeTargetRefV2 | None) -> str | None:
    return (
        None if value is None else json.dumps(asdict(value), sort_keys=True, separators=(",", ":"))
    )


def _optional_text(value: object | None) -> str | None:
    return None if value is None else str(value)
