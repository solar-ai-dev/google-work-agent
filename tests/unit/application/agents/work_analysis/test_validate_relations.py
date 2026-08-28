from __future__ import annotations

import pytest

from google_work_agent.application.agents.work_analysis.validate_relations import validate_relations


def test_guarded_relation_requires_deterministic_validator_code() -> None:
    facts = [
        {"fact_id": "a", "fact_type": "TASK", "value": "x", "evidence_refs": ["e1"]},
        {"fact_id": "b", "fact_type": "TASK", "value": "x", "evidence_refs": ["e2"]},
    ]
    with pytest.raises(ValueError, match="guarded relation"):
        validate_relations(
            [
                {
                    "relation_type": "DUPLICATES",
                    "left_ref": "a",
                    "right_ref": "b",
                    "evidence_refs": ["e1", "e2"],
                }
            ],
            work_facts=facts,
            validator=lambda _relation, _left, _right: {"accepted": True, "validator_codes": []},
        )


def test_validated_duplicate_can_mark_action_not_required() -> None:
    facts = [
        {"fact_id": "a", "fact_type": "TASK", "value": "x", "evidence_refs": ["e1"]},
        {"fact_id": "b", "fact_type": "TASK", "value": "x", "evidence_refs": ["e2"]},
    ]
    result = validate_relations(
        [
            {
                "relation_type": "DUPLICATES",
                "left_ref": "a",
                "right_ref": "b",
                "evidence_refs": ["e1", "e2"],
            }
        ],
        work_facts=facts,
        validator=lambda _relation, _left, _right: {
            "accepted": True,
            "validator_codes": ["EXACT_TASK_DUPLICATE"],
            "action_necessity": "NOT_REQUIRED",
        },
    )
    assert result["action_necessity"] == "NOT_REQUIRED"
    assert result["validated_relations"][0]["validator_codes"] == ["EXACT_TASK_DUPLICATE"]
