from __future__ import annotations

import pytest

from google_work_agent.application.orchestration.assemble_planning_answer import (
    PlanningAnswerV2ValidationError,
    materialize_answer_draft_v2,
    validate_answer_draft_candidate_v2,
)


def _candidate():
    return {
        "schema_version": 2,
        "answer": "Harbor 메일은 공급망 패치가 필요하다고 보고합니다.",
        "evidence_refs": ["ev-1"],
    }


def _meta():
    return {
        "artifact_id": "answer-1",
        "revision": 1,
        "based_on": [
            {"artifact_id": "route-output-1", "revision": 1},
            {"artifact_id": "analysis-1", "revision": 1},
            {"artifact_id": "retrieval-1", "revision": 1},
        ],
    }


def test_candidate_matches_r86_answer_contract() -> None:
    result = validate_answer_draft_candidate_v2(
        _candidate(), allowed_evidence_refs={"ev-1"}
    )
    assert set(result) == {"schema_version", "answer", "evidence_refs"}
    assert result["schema_version"] == 2


def test_candidate_rejects_legacy_status_authority() -> None:
    candidate = {**_candidate(), "status": "ANSWER_ONLY"}
    with pytest.raises(PlanningAnswerV2ValidationError, match="keys mismatch"):
        validate_answer_draft_candidate_v2(candidate, allowed_evidence_refs={"ev-1"})


def test_candidate_rejects_unavailable_evidence() -> None:
    with pytest.raises(PlanningAnswerV2ValidationError, match="unavailable evidence"):
        validate_answer_draft_candidate_v2(_candidate(), allowed_evidence_refs=set())


def test_materialize_preserves_explicit_lineage() -> None:
    result = materialize_answer_draft_v2(
        _candidate(), meta=_meta(), allowed_evidence_refs={"ev-1"}
    )
    assert result == {
        "schema_version": 2,
        "meta": _meta(),
        "answer": _candidate()["answer"],
        "evidence_refs": ["ev-1"],
    }
