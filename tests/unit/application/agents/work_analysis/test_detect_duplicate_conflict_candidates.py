from google_work_agent.application.agents.work_analysis import (
    detect_duplicate_conflict_candidates,
)

from .conftest import FakeRuntime, fact, prompt_ref


def test_duplicate_is_never_promoted_by_candidate_operation() -> None:
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
    result = detect_duplicate_conflict_candidates.detect_duplicate_conflict_candidates(
        work_facts=[fact("f1"), fact("f2")],
        entity_relations=[],
        evidence=[],
        source_state={},
        llm_runtime=FakeRuntime(output),
        prompt_ref=prompt_ref(
            "work_analysis.detect_duplicate_conflict_candidates",
            "detect_duplicate_conflict_candidates",
        ),
        allowed_evidence_refs={"ev-1"},
        requested_mode="AUTO",
    )
    assert result == output["relation_candidates"]
    assert "validated_relations" not in output
