from google_work_agent.application.agents.work_analysis import (
    detect_duplicate_conflict_candidates,
)
from tests.support.work_analysis import WorkAnalysisRuntimeFake, fact, prompt_ref


def test_duplicate_is__never_promoted__by_candidate_operation() -> None:
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
    runtime = WorkAnalysisRuntimeFake(output)
    result = detect_duplicate_conflict_candidates.detect_duplicate_conflict_candidates(
        work_facts=[fact("f1"), fact("f2")],
        entity_relations=[],
        evidence=[],
        source_state={},
        llm_runtime=runtime,
        prompt_ref=prompt_ref(
            "work_analysis.detect_duplicate_conflict_candidates",
            "detect_duplicate_conflict_candidates",
        ),
        allowed_evidence_refs={"ev-1"},
        requested_mode="AUTO",
    )
    assert result == output["relation_candidates"]
    assert len(runtime.calls) == 1
    assert "validated_relations" not in output
    output_schema = runtime.calls[0]["output_schema"]
    candidate_schema = output_schema.json_schema["properties"]["relation_candidates"]["items"]
    properties = candidate_schema["properties"]
    assert properties["source_fact_id"]["enum"] == ["f1", "f2"]
    assert properties["target_fact_id"]["enum"] == ["f1", "f2"]
    assert properties["evidence_refs"]["items"]["enum"] == ["ev-1"]


def test_duplicate_candidates__with_fewer_than_two_facts__materialize_empty_without_llm() -> None:
    runtime = WorkAnalysisRuntimeFake({"relation_candidates": []})

    result = detect_duplicate_conflict_candidates.detect_duplicate_conflict_candidates(
        work_facts=[fact("f1")],
        entity_relations=[],
        evidence=[],
        source_state={},
        llm_runtime=runtime,
        prompt_ref=prompt_ref(
            "work_analysis.detect_duplicate_conflict_candidates",
            "detect_duplicate_conflict_candidates",
        ),
        allowed_evidence_refs=set(),
        requested_mode="AUTO",
    )

    assert result == []
    assert runtime.calls == []
