import pytest

from google_work_agent.application.agents.work_analysis.resolve_temporal_dependencies import (
    resolve_temporal_dependencies,
)
from tests.support.work_analysis import WorkAnalysisRuntimeFake, fact, prompt_ref


def test_temporal_dependency__preserves_candidate__boundary() -> None:
    output = {
        "relation_candidates": [
            {
                "relation_id": "r1",
                "kind": "DUE_AT",
                "source_fact_id": "f1",
                "target_fact_id": "f2",
                "evidence_refs": ["ev-1"],
            }
        ]
    }
    result = resolve_temporal_dependencies(
        work_facts=[fact("f1"), fact("f2", "DEADLINE")],
        evidence=[],
        availability_results=[],
        llm_runtime=WorkAnalysisRuntimeFake(output),
        prompt_ref=prompt_ref(
            "work_analysis.resolve_temporal_dependencies", "resolve_temporal_dependencies"
        ),
        allowed_evidence_refs={"ev-1"},
        requested_mode="AUTO",
    )
    assert result == output["relation_candidates"]


def test_temporal_dependency__rejects_unknown__kind() -> None:
    output = {
        "relation_candidates": [
            {
                "relation_id": "r1",
                "kind": "BEFORE",
                "source_fact_id": "f1",
                "target_fact_id": "f2",
                "evidence_refs": ["ev-1"],
            }
        ]
    }
    with pytest.raises(ValueError, match="temporal relation"):
        resolve_temporal_dependencies(
            work_facts=[fact("f1"), fact("f2")],
            evidence=[],
            availability_results=[],
            llm_runtime=WorkAnalysisRuntimeFake(output),
            prompt_ref=prompt_ref(
                "work_analysis.resolve_temporal_dependencies", "resolve_temporal_dependencies"
            ),
            allowed_evidence_refs={"ev-1"},
            requested_mode="AUTO",
        )


def test_temporal_dependency__binds_dynamic_references__before_inference() -> None:
    runtime = WorkAnalysisRuntimeFake({"relation_candidates": []})

    resolve_temporal_dependencies(
        work_facts=[fact("f1"), fact("f2")],
        evidence=[],
        availability_results=[],
        llm_runtime=runtime,
        prompt_ref=prompt_ref(
            "work_analysis.resolve_temporal_dependencies", "resolve_temporal_dependencies"
        ),
        allowed_evidence_refs={"ev-1", "ev-2"},
        requested_mode="LOCAL_GPU",
    )

    output_schema = runtime.calls[0]["output_schema"]
    item_schema = output_schema.json_schema["properties"]["relation_candidates"]["items"]
    assert item_schema["properties"]["source_fact_id"]["enum"] == ["f1", "f2"]
    assert item_schema["properties"]["target_fact_id"]["enum"] == ["f1", "f2"]
    assert item_schema["properties"]["evidence_refs"] == {
        "type": "array",
        "minItems": 1,
        "uniqueItems": True,
        "items": {"type": "string", "enum": ["ev-1", "ev-2"]},
    }


def test_temporal_dependency__rejects_same_fact__relation() -> None:
    output = {
        "relation_candidates": [
            {
                "relation_id": "r1",
                "kind": "RELATED_TO",
                "source_fact_id": "f1",
                "target_fact_id": "f1",
                "evidence_refs": ["ev-1"],
            }
        ]
    }

    with pytest.raises(ValueError, match="identity or operands"):
        resolve_temporal_dependencies(
            work_facts=[fact("f1")],
            evidence=[],
            availability_results=[],
            llm_runtime=WorkAnalysisRuntimeFake(output),
            prompt_ref=prompt_ref(
                "work_analysis.resolve_temporal_dependencies", "resolve_temporal_dependencies"
            ),
            allowed_evidence_refs={"ev-1"},
            requested_mode="LOCAL_GPU",
        )
