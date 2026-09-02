import pytest

from google_work_agent.application.agents.work_analysis.validate_work_analysis import (
    validate_work_analysis,
)


def _result() -> dict[str, object]:
    return {
        "schema_version": 2,
        "meta": {
            "artifact_id": "analysis-1",
            "revision": 1,
            "based_on": [{"artifact_id": "intent-1", "revision": 1}],
        },
        "work_facts": [
            {
                "fact_id": "f1",
                "kind": "TASK",
                "subject": "report",
                "value": "submit",
                "derivation": "EXPLICIT",
                "evidence_refs": ["ev-1"],
            }
        ],
        "relations": [],
        "ambiguities": [],
        "risks": [],
        "action_necessity": "REQUIRED",
        "action_necessity_reason": "REQUEST_REQUIRES_ACTION",
        "policy_confirmation_receipt_refs": [],
        "evidence_refs": ["ev-1"],
    }


def test_validate_work__analysis_accepts__exact_v2_contract() -> None:
    assert validate_work_analysis(_result(), allowed_evidence_refs={"ev-1"}) == _result()


def test_validate_work_analysis__rejects_legacy_risk__and_extra_field() -> None:
    value = _result()
    value["risks"] = [
        {
            "kind": "DEADLINE_RISK",
            "severity": "BLOCKING",
            "description": "legacy",
            "evidence_refs": ["ev-1"],
        }
    ]
    with pytest.raises(ValueError, match="WorkRiskV1"):
        validate_work_analysis(value, allowed_evidence_refs={"ev-1"})

    value = _result()
    value["legacy"] = True
    with pytest.raises(ValueError, match="keys/schema_version"):
        validate_work_analysis(value, allowed_evidence_refs={"ev-1"})
