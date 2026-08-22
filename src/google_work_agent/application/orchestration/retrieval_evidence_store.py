"""Run-memory store for already materialized Retrieval evidence only."""

from __future__ import annotations

from threading import Lock
from typing import cast

from google_work_agent.application.orchestration.handoff_contracts import (
    EvidenceDraftV1,
    RetrievalResultV1,
)


class EvidenceResolutionError(ValueError):
    """Requested evidence is unavailable or conflicts within its run."""


class RunScopedEvidenceStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._by_run: dict[str, dict[str, EvidenceDraftV1]] = {}

    def put(self, *, run_id: str, evidence_drafts: list[EvidenceDraftV1]) -> None:
        with self._lock:
            run_entries = self._by_run.setdefault(run_id, {})
            for draft in evidence_drafts:
                existing = run_entries.get(draft["evidence_id"])
                if existing is not None and existing != draft:
                    raise EvidenceResolutionError("conflicting evidence id in retrieval run")
                run_entries[draft["evidence_id"]] = cast(EvidenceDraftV1, dict(draft))

    def resolve(self, *, run_id: str, evidence_refs: list[str]) -> list[EvidenceDraftV1]:
        with self._lock:
            run_entries = self._by_run.get(run_id, {})
            resolved: list[EvidenceDraftV1] = []
            for evidence_ref in evidence_refs:
                draft = run_entries.get(evidence_ref)
                if draft is None:
                    raise EvidenceResolutionError("evidence reference is unavailable for this run")
                resolved.append(cast(EvidenceDraftV1, dict(draft)))
            return resolved

    def discard_run(self, *, run_id: str) -> None:
        with self._lock:
            self._by_run.pop(run_id, None)


def resolve_evidence_projection(
    *,
    store: RunScopedEvidenceStore,
    run_id: str,
    retrieval_result: RetrievalResultV1,
) -> list[EvidenceDraftV1]:
    """Resolve only the canonical result's ordered evidence references."""
    return store.resolve(run_id=run_id, evidence_refs=retrieval_result["evidence_refs"])
