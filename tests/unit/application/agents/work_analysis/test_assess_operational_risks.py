import pytest

from google_work_agent.application.agents.work_analysis.assess_operational_risks import (
    assess_operational_risks,
)
from tests.support.work_analysis import WorkAnalysisRuntimeFake, fact, intent, prompt_ref


def test_assess_operational__risks_uses__canonical_risk_vocabulary() -> None:
    output = {
        "risks": [
            {
                "kind": "DEADLINE_RISK",
                "severity": "HIGH",
                "description": "deadline is near",
                "evidence_refs": ["ev-1"],
            }
        ],
        "action_necessity_candidate": "REQUIRED",
        "action_necessity_reason": "REQUEST_REQUIRES_ACTION",
        "evidence_refs": ["ev-1"],
    }
    runtime = WorkAnalysisRuntimeFake(output)

    result = assess_operational_risks(
        request_intent=intent(),
        work_facts=[fact("f1")],
        validated_relations=[],
        evidence=[],
        llm_runtime=runtime,
        prompt_ref=prompt_ref("work_analysis.assess_operational_risks", "assess_operational_risks"),
        allowed_evidence_refs={"ev-1"},
        requested_mode="AUTO",
    )

    assert result == output


def test_assess_operational__risks_rejects__legacy_severity() -> None:
    runtime = WorkAnalysisRuntimeFake(
        {
            "risks": [
                {
                    "kind": "DEADLINE_RISK",
                    "severity": "BLOCKING",
                    "description": "legacy",
                    "evidence_refs": ["ev-1"],
                }
            ],
            "action_necessity_candidate": "UNDETERMINED",
            "action_necessity_reason": None,
            "evidence_refs": ["ev-1"],
        }
    )
    with pytest.raises(ValueError, match="operational-risk schema"):
        assess_operational_risks(
            request_intent=intent(),
            work_facts=[fact("f1")],
            validated_relations=[],
            evidence=[],
            llm_runtime=runtime,
            prompt_ref=prompt_ref(
                "work_analysis.assess_operational_risks", "assess_operational_risks"
            ),
            allowed_evidence_refs={"ev-1"},
            requested_mode="AUTO",
        )


def test_assess_operational__risks_binds_current_evidence__before_inference() -> None:
    runtime = WorkAnalysisRuntimeFake(
        {
            "risks": [],
            "action_necessity_candidate": "NOT_REQUIRED",
            "action_necessity_reason": None,
            "evidence_refs": [],
        }
    )

    assess_operational_risks(
        request_intent=intent(),
        work_facts=[fact("f1")],
        validated_relations=[],
        evidence=[],
        llm_runtime=runtime,
        prompt_ref=prompt_ref(
            "work_analysis.assess_operational_risks", "assess_operational_risks"
        ),
        allowed_evidence_refs={"ev-2", "ev-1"},
        requested_mode="LOCAL_GPU",
    )

    output_schema = runtime.calls[0]["output_schema"]
    properties = output_schema.json_schema["properties"]
    assert properties["evidence_refs"] == {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "string", "enum": ["ev-1", "ev-2"]},
    }
    assert properties["risks"]["items"]["properties"]["evidence_refs"] == {
        "type": "array",
        "minItems": 1,
        "uniqueItems": True,
        "items": {"type": "string", "enum": ["ev-1", "ev-2"]},
    }
