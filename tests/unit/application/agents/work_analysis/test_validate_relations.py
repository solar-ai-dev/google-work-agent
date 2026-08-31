from typing import cast

import pytest

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    CurrentSourceRelationV1,
    WorkRelationCandidateV1,
)
from google_work_agent.application.agents.work_analysis.validate_relations import validate_relations

from .conftest import fact


def _candidate(kind: str = "DUPLICATES") -> WorkRelationCandidateV1:
    return cast(
        WorkRelationCandidateV1,
        {
            "relation_id": "r1",
            "kind": kind,
            "source_fact_id": "f1",
            "target_fact_id": "f2",
            "evidence_refs": ["ev-1"],
        },
    )


def test_guarded_candidate_without_current_source_truth_is_not_final() -> None:
    result = validate_relations(
        work_facts=[fact("f1"), fact("f2")],
        entity_relation_candidates=[],
        temporal_dependency_candidates=[],
        duplicate_conflict_candidates=[_candidate()],
        current_source_relations=[],
        allowed_evidence_refs={"ev-1"},
    )
    assert result["validated_relations"] == []
    assert result["relation_validation_ambiguities"][0]["requires_confirmation"] is True


def test_current_source_truth_promotes_exact_guarded_relation() -> None:
    candidate = _candidate()
    current_source_truth: CurrentSourceRelationV1 = {
        "relation_id": "source-relation-7",
        "kind": "DUPLICATES",
        "source_fact_id": "f1",
        "target_fact_id": "f2",
        "evidence_refs": ["ev-1"],
    }
    result = validate_relations(
        work_facts=[fact("f1"), fact("f2")],
        entity_relation_candidates=[],
        temporal_dependency_candidates=[],
        duplicate_conflict_candidates=[candidate],
        current_source_relations=[current_source_truth],
        allowed_evidence_refs={"ev-1"},
    )
    assert result["validated_relations"] == [candidate]
    assert result["relation_validation_ambiguities"] == []


def test_unknown_or_free_text_relation_kind_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown WorkRelationV1"):
        validate_relations(
            work_facts=[fact("f1"), fact("f2")],
            entity_relation_candidates=[_candidate("OWNS")],
            temporal_dependency_candidates=[],
            duplicate_conflict_candidates=[],
            current_source_relations=[],
            allowed_evidence_refs={"ev-1"},
        )
