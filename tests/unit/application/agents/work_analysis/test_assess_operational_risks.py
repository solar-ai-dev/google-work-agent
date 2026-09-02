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
