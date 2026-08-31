import pytest

from google_work_agent.application.agents.work_analysis.resolve_entity_relations import (
    resolve_entity_relations,
)

from .conftest import FakeRuntime, fact, prompt_ref


def test_entity_relation_is_candidate_only() -> None:
    output = {
        "relation_candidates": [
            {
                "relation_id": "r1",
                "kind": "ASSIGNED_TO",
                "source_fact_id": "f1",
                "target_fact_id": "f2",
                "evidence_refs": ["ev-1"],
            }
        ]
    }
    result = resolve_entity_relations(
        work_facts=[fact("f1"), fact("f2", "PERSON")],
        evidence=[],
        llm_runtime=FakeRuntime(output),
        prompt_ref=prompt_ref("work_analysis.resolve_entity_relations", "resolve_entity_relations"),
        allowed_evidence_refs={"ev-1"},
        requested_mode="AUTO",
    )
    assert result == output["relation_candidates"]


def test_entity_relation_rejects_guarded_kind() -> None:
    output = {
        "relation_candidates": [
            {
                "relation_id": "r1",
                "kind": "DUPLICATES",
                "source_fact_id": "f1",
                "target_fact_id": "f2",
                "evidence_refs": ["ev-1"],
            }
        ]
    }
    with pytest.raises(ValueError, match="entity relation"):
        resolve_entity_relations(
            work_facts=[fact("f1"), fact("f2")],
            evidence=[],
            llm_runtime=FakeRuntime(output),
            prompt_ref=prompt_ref(
                "work_analysis.resolve_entity_relations", "resolve_entity_relations"
            ),
            allowed_evidence_refs={"ev-1"},
            requested_mode="AUTO",
        )
