import pytest

from google_work_agent.application.agents.work_analysis.resolve_temporal_dependencies import (
    resolve_temporal_dependencies,
)
from tests.support.work_analysis import WorkAnalysisRuntimeFake, fact, prompt_ref


def test_temporal_dependency_preserves_candidate_boundary() -> None:
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


def test_temporal_dependency_rejects_unknown_kind() -> None:
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
