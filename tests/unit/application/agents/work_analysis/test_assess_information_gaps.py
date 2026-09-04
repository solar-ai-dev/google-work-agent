from typing import cast

import pytest

from google_work_agent.application.agents.work_analysis.assess_information_gaps import (
    assess_information_gaps,
    combine_information_gap_assessment,
)
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from tests.support.work_analysis import WorkAnalysisRuntimeFake, fact, intent, prompt_ref


def test_assess_information_gaps__uses_exact_prompt__and_bounded_retrieval_need() -> None:
    output = {
        "disposition": "NEEDS_MORE_DATA",
        "ambiguities": [],
        "retrieval_needs": [
            {"required_information": "current due date", "reason_codes": ["DUE_DATE_MISSING"]}
        ],
        "evidence_refs": ["ev-1"],
        "reason_codes": ["DUE_DATE_MISSING"],
    }
    runtime = WorkAnalysisRuntimeFake(output)

    result = assess_information_gaps(
        request_intent=intent(),
        work_facts=[fact("f1")],
        evidence=[],
        llm_runtime=runtime,
        prompt_ref=prompt_ref("work_analysis.assess_information_gaps", "assess_information_gaps"),
        allowed_evidence_refs={"ev-1"},
        requested_mode="AUTO",
    )

    assert result == output
    assert (
        cast(PromptReference, runtime.calls[0]["prompt_ref"]).prompt_id
        == "work_analysis.assess_information_gaps"
    )


def test_assess_information__gaps_rejects__unbounded_evidence() -> None:
    runtime = WorkAnalysisRuntimeFake(
        {
            "disposition": "COMPLETE",
            "ambiguities": [],
            "retrieval_needs": [],
            "evidence_refs": ["stale"],
        }
    )
    with pytest.raises(ValueError, match="invalid information-gap schema"):
        assess_information_gaps(
            request_intent=intent(),
            work_facts=[fact("f1")],
            evidence=[],
            llm_runtime=runtime,
            prompt_ref=prompt_ref(
                "work_analysis.assess_information_gaps", "assess_information_gaps"
            ),
            allowed_evidence_refs={"ev-1"},
            requested_mode="AUTO",
        )


def test_assess_information__gaps_exposes_disposition_invariants__to_repair() -> None:
    runtime = WorkAnalysisRuntimeFake(
        {
            "disposition": "COMPLETE",
            "ambiguities": [],
            "retrieval_needs": [],
            "evidence_refs": ["ev-1"],
        }
    )

    assess_information_gaps(
        request_intent=intent(),
        work_facts=[fact("f1")],
        evidence=[],
        llm_runtime=runtime,
        prompt_ref=prompt_ref("work_analysis.assess_information_gaps", "assess_information_gaps"),
        allowed_evidence_refs={"ev-1"},
        requested_mode="LOCAL_GPU",
    )

    output_schema = runtime.calls[0]["output_schema"]
    schema = output_schema.json_schema
    branches = {branch["properties"]["disposition"]["const"]: branch for branch in schema["oneOf"]}
    assert branches["COMPLETE"]["properties"]["evidence_refs"]["items"]["enum"] == ["ev-1"]
    assert set(branches["COMPLETE"]["required"]) == {
        "disposition",
        "ambiguities",
        "retrieval_needs",
        "evidence_refs",
    }
    assert branches["COMPLETE"]["properties"]["retrieval_needs"]["maxItems"] == 0
    assert branches["NEEDS_MORE_DATA"]["properties"]["retrieval_needs"]["minItems"] == 1
    assert "question" in branches["NEEDS_CONFIRMATION"]["required"]


def test_read_only_missing_evidence__does_not_interrupt_for_user_confirmation() -> None:
    request_intent = intent()
    request_intent["requested_effect_hints"] = ["READ"]
    result = combine_information_gap_assessment(
        assessment={
            "disposition": "NEEDS_CONFIRMATION",
            "ambiguities": [
                {
                    "code": "MISSING_APPROVED_BUDGET",
                    "description": "The evidence does not include an approved budget.",
                    "requires_confirmation": True,
                    "evidence_refs": ["ev-1"],
                }
            ],
            "retrieval_needs": [],
            "evidence_refs": ["ev-1"],
            "question": "Please provide the approved budget.",
            "options": [],
            "reason_codes": ["MISSING_APPROVED_BUDGET"],
        },
        relation_ambiguities=[],
        request_intent=request_intent,
        has_confirmation_response=False,
    )

    assert result == {
        "disposition": "COMPLETE",
        "ambiguities": [
            {
                "code": "MISSING_APPROVED_BUDGET",
                "description": "The evidence does not include an approved budget.",
                "requires_confirmation": False,
                "evidence_refs": ["ev-1"],
            }
        ],
        "retrieval_needs": [],
        "evidence_refs": ["ev-1"],
    }


def test_write_user_owned_choice__preserves_confirmation() -> None:
    request_intent = intent()
    request_intent["requested_effect_hints"] = ["CREATE"]
    assessment = {
        "disposition": "NEEDS_CONFIRMATION",
        "ambiguities": [],
        "retrieval_needs": [],
        "evidence_refs": ["ev-1"],
        "question": "Which calendar should receive the event?",
        "options": ["primary", "team"],
        "reason_codes": ["MISSING_CALENDAR_CHOICE"],
    }

    assert (
        combine_information_gap_assessment(
            assessment=assessment,
            relation_ambiguities=[],
            request_intent=request_intent,
            has_confirmation_response=False,
        )
        == assessment
    )
