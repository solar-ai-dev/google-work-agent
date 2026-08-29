"""Read the current Run-scoped external-LLM transfer disclosure."""

from dataclasses import dataclass
from threading import Lock
from typing import Literal

from google_work_agent.application.use_cases.sse_event.project_run_event import (
    ProjectRunEventCommand,
    ProjectRunEventHandler,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.ports.system.checkpoint_port import CheckpointPort
from google_work_agent.ports.system.contracts.external_llm_transfer_scope import (
    ExternalLlmTransferScopeV1,
)


@dataclass(frozen=True, slots=True)
class ProjectExternalLlmTransferScopeQueryV1:
    schema_version: Literal[1]
    run_id: str
    source_kinds: tuple[str, ...] | None = None
    data_classes: (
        tuple[
            Literal["USER_REQUEST", "RESOURCE_METADATA", "EVIDENCE_EXCERPT", "PLAN_CONTEXT"],
            ...,
        ]
        | None
    ) = None
    occurred_at_ms: int | None = None


class ProjectExternalLlmTransferScopeHandler:
    def __init__(
        self,
        checkpoint: CheckpointPort,
        project_run_event: ProjectRunEventHandler | None = None,
    ) -> None:
        self._checkpoint = checkpoint
        self._project_run_event = project_run_event
        self._publication_lock = Lock()
        self._announced_scopes: set[tuple[str, int, str]] = set()

    def __call__(
        self, query: ProjectExternalLlmTransferScopeQueryV1
    ) -> ExternalLlmTransferScopeV1 | None:
        if query.schema_version != 1 or not query.run_id.strip():
            raise ValueError("invalid external-LLM scope query")
        if query.source_kinds is None and query.data_classes is None:
            return self._checkpoint.load_external_llm_scope(query.run_id)
        if query.source_kinds is None or query.data_classes is None:
            raise ValueError("source_kinds and data_classes must be projected together")
        source_kinds = sorted(set(query.source_kinds))
        data_classes = sorted(set(query.data_classes))
        if not source_kinds or not data_classes or any(not item.strip() for item in source_kinds):
            raise ValueError("external-LLM scope must be non-empty")
        if self._project_run_event is not None and (
            query.occurred_at_ms is None or query.occurred_at_ms < 0
        ):
            raise ValueError("scope publication event requires occurred_at_ms")
        scope_hash = calculate_canonical_json_hash(
            {
                "run_id": query.run_id,
                "source_kinds": source_kinds,
                "data_classes": data_classes,
            }
        )
        with self._publication_lock:
            current = self._checkpoint.load_external_llm_scope(query.run_id)
            if current is not None and current.scope_hash == scope_hash:
                scope = current
            else:
                scope = ExternalLlmTransferScopeV1(
                    schema_version=1,
                    run_id=query.run_id,
                    scope_revision=1 if current is None else current.scope_revision + 1,
                    scope_hash=scope_hash,
                    source_kinds=source_kinds,
                    data_classes=data_classes,
                )
                self._checkpoint.store_external_llm_scope(scope)
                self._checkpoint.flush()
            publication_key = (scope.run_id, scope.scope_revision, scope.scope_hash)
            if (
                self._project_run_event is not None
                and publication_key not in self._announced_scopes
            ):
                assert query.occurred_at_ms is not None
                self._project_run_event(
                    ProjectRunEventCommand(
                        run_id=query.run_id,
                        occurred_at_ms=query.occurred_at_ms,
                        event_type="EXTERNAL_LLM_SCOPE_PUBLISHED",
                        payload={
                            "scope_revision": scope.scope_revision,
                            "scope_hash": scope.scope_hash,
                            "source_kinds": list(scope.source_kinds),
                            "data_classes": list(scope.data_classes),
                        },
                    )
                )
                self._announced_scopes.add(publication_key)
            return scope


__all__ = [
    "ExternalLlmTransferScopeV1",
    "ProjectExternalLlmTransferScopeHandler",
    "ProjectExternalLlmTransferScopeQueryV1",
]
