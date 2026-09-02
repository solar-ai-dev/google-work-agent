import pytest

from google_work_agent.adapters.system.memory.retrieval_evidence_store import (
    EvidenceResolutionError,
    RunScopedEvidenceStore,
    resolve_evidence_projection,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    EvidenceDraftV1,
)


def test_resolves_requested__refs_in__requested_order() -> None:
    store = RunScopedEvidenceStore()
    first, second = _draft("evidence-1"), _draft("evidence-2")
    store.put(run_id="run-1", evidence_drafts=[first, second])

    assert store.resolve(run_id="run-1", evidence_refs=["evidence-2", "evidence-1"]) == [
        second,
        first,
    ]


def test_unknown_and__cross_run__refs_fail_closed() -> None:
    store = RunScopedEvidenceStore()
    store.put(run_id="run-1", evidence_drafts=[_draft("evidence-1")])

    with pytest.raises(EvidenceResolutionError):
        store.resolve(run_id="run-1", evidence_refs=["missing"])
    with pytest.raises(EvidenceResolutionError):
        store.resolve(run_id="run-2", evidence_refs=["evidence-1"])


def test_same_id_is__idempotent_but_conflicting__content_fails_closed() -> None:
    store = RunScopedEvidenceStore()
    draft = _draft("evidence-1")
    store.put(run_id="run-1", evidence_drafts=[draft])
    store.put(run_id="run-1", evidence_drafts=[draft])

    conflicting = _draft("evidence-1")
    conflicting["excerpt"] = "other"
    with pytest.raises(EvidenceResolutionError):
        store.put(run_id="run-1", evidence_drafts=[conflicting])


def test_discard_removes__run__evidence() -> None:
    store = RunScopedEvidenceStore()
    store.put(run_id="run-1", evidence_drafts=[_draft("evidence-1")])
    store.discard_run(run_id="run-1")

    with pytest.raises(EvidenceResolutionError):
        store.resolve(run_id="run-1", evidence_refs=["evidence-1"])


def test_projection_resolves__only_result__refs() -> None:
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
            "excluded_segment_ids": [],
            "source_resource_refs": ["gmail_thread:thread-1"],
            "source_statuses": [],
            "availability_results": [],
            "missing_information": [],
            "retrieval_rounds": 1,
        },
    ) == [draft]


def _draft(evidence_id: str) -> EvidenceDraftV1:
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
