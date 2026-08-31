import pytest

from google_work_agent.adapters.system.memory.retrieval_evidence_store import (
    EvidenceResolutionError,
    RunScopedEvidenceStore,
    resolve_evidence_projection,
)


def test_resolves_requested_refs_in_requested_order() -> None:
    store = RunScopedEvidenceStore()
    first, second = _draft("evidence-1"), _draft("evidence-2")
    store.put(run_id="run-1", evidence_drafts=[first, second])

    assert store.resolve(run_id="run-1", evidence_refs=["evidence-2", "evidence-1"]) == [
        second,
        first,
    ]


def test_unknown_and_cross_run_refs_fail_closed() -> None:
    store = RunScopedEvidenceStore()
    store.put(run_id="run-1", evidence_drafts=[_draft("evidence-1")])

    with pytest.raises(EvidenceResolutionError):
        store.resolve(run_id="run-1", evidence_refs=["missing"])
    with pytest.raises(EvidenceResolutionError):
        store.resolve(run_id="run-2", evidence_refs=["evidence-1"])


def test_same_id_is_idempotent_but_conflicting_content_fails_closed() -> None:
    store = RunScopedEvidenceStore()
    draft = _draft("evidence-1")
    store.put(run_id="run-1", evidence_drafts=[draft])
    store.put(run_id="run-1", evidence_drafts=[draft])

    conflicting = {**draft, "excerpt": "other"}
    with pytest.raises(EvidenceResolutionError):
        store.put(run_id="run-1", evidence_drafts=[conflicting])


def test_discard_removes_run_evidence() -> None:
    store = RunScopedEvidenceStore()
    store.put(run_id="run-1", evidence_drafts=[_draft("evidence-1")])
    store.discard_run(run_id="run-1")

    with pytest.raises(EvidenceResolutionError):
        store.resolve(run_id="run-1", evidence_refs=["evidence-1"])


def test_projection_resolves_only_result_refs() -> None:
    store = RunScopedEvidenceStore()
    draft = _draft("evidence-1")
    store.put(run_id="run-1", evidence_drafts=[draft])

    assert resolve_evidence_projection(
        store=store,
        run_id="run-1",
        retrieval_result={
            "schema_version": 1,
            "meta": {"artifact_id": "retrieval-1", "revision": 1, "based_on": []},
            "coverage": "SUFFICIENT",
            "context_bundle_ref": None,
            "evidence_refs": ["evidence-1"],
            "selected_segment_ids": ["segment-1"],
            "source_resource_refs": ["gmail_thread:thread-1"],
            "source_statuses": [],
            "missing_information": [],
            "retrieval_rounds": 1,
        },
    ) == [draft]


def _draft(evidence_id: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "evidence_id": evidence_id,
        "resource_handle": "gmail_thread:thread-1",
        "segment_id": "segment-1",
        "kind": "excerpt",
        "excerpt": "bounded evidence",
        "locator": None,
        "reason_codes": ["SUPPORTS"],
    }
