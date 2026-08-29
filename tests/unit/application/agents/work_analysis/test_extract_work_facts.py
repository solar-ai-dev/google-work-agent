import pytest

from google_work_agent.application.agents.work_analysis.extract_work_facts import extract_work_facts

from .conftest import TRACE, FakeRuntime, prompt_ref


def test_extract_work_facts_uses_exact_contract_and_bounded_evidence() -> None:
    output = {
        "fact_candidates": [
            {
                "fact_id": "f1",
                "kind": "TASK",
                "subject": "report",
                "value": "submit",
                "derivation": "EXPLICIT",
                "evidence_refs": ["ev-1"],
            }
        ]
    }
    runtime = FakeRuntime(output)
    result = extract_work_facts(
        semantic_input={"user_request": "submit", "request_intent": {}, "evidence": []},
        llm_runtime=runtime,
        prompt_ref=prompt_ref("work_analysis.extract_work_facts", "extract_work_facts"),
        allowed_evidence_refs={"ev-1"},
        trace_context=TRACE,
    )
    assert result == output["fact_candidates"]
    assert runtime.calls[0]["prompt_ref"].prompt_id == "work_analysis.extract_work_facts"


def test_extract_work_facts_rejects_old_or_stale_schema() -> None:
    runtime = FakeRuntime(
        {
            "fact_candidates": [
                {"fact_id": "f1", "fact_type": "TASK", "value": "x", "evidence_refs": ["stale"]}
            ]
        }
    )
    with pytest.raises(ValueError, match="WorkFactV1"):
        extract_work_facts(
            semantic_input={"user_request": "x", "request_intent": {}, "evidence": []},
            llm_runtime=runtime,
            prompt_ref=prompt_ref("work_analysis.extract_work_facts", "extract_work_facts"),
            allowed_evidence_refs={"ev-1"},
            trace_context=TRACE,
        )
