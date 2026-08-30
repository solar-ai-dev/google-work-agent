import pytest

from google_work_agent.application.agents.work_analysis.assess_information_gaps import (
    assess_information_gaps,
)

from .conftest import TRACE, FakeRuntime, fact, prompt_ref


def test_assess_information_gaps_uses_exact_prompt_and_bounded_retrieval_need() -> None:
    output = {
        "disposition": "NEEDS_MORE_DATA",
        "ambiguities": [],
        "retrieval_needs": [
            {"required_information": "current due date", "reason_codes": ["DUE_DATE_MISSING"]}
        ],
        "evidence_refs": ["ev-1"],
        "reason_codes": ["DUE_DATE_MISSING"],
    }
    runtime = FakeRuntime(output)

    result = assess_information_gaps(
        request_intent={},  # type: ignore[arg-type]
        work_facts=[fact("f1")],  # type: ignore[list-item]
        evidence=[],
        llm_runtime=runtime,
        prompt_ref=prompt_ref("work_analysis.assess_information_gaps", "assess_information_gaps"),
        allowed_evidence_refs={"ev-1"},
        trace_context=TRACE,
    )

    assert result == output
    assert runtime.calls[0]["prompt_ref"].prompt_id == "work_analysis.assess_information_gaps"


def test_assess_information_gaps_rejects_unbounded_evidence() -> None:
    runtime = FakeRuntime(
        {
            "disposition": "COMPLETE",
            "ambiguities": [],
            "retrieval_needs": [],
            "evidence_refs": ["stale"],
        }
    )
    with pytest.raises(ValueError, match="outside current RetrievalResultV1"):
        assess_information_gaps(
            request_intent={},  # type: ignore[arg-type]
            work_facts=[fact("f1")],  # type: ignore[list-item]
            evidence=[],
            llm_runtime=runtime,
            prompt_ref=prompt_ref(
                "work_analysis.assess_information_gaps", "assess_information_gaps"
            ),
            allowed_evidence_refs={"ev-1"},
            trace_context=TRACE,
        )
