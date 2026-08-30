"""Negative proof for retired broad Planning ANSWER helpers."""

import google_work_agent.application.orchestration.optional_agent_inputs as optional_inputs


def test_broad_optional_input_answer_authority_is_absent() -> None:
    assert not hasattr(optional_inputs, "CanonicalOptionalInputPlanningAgent")
    assert not hasattr(optional_inputs, "validate_answer_with_optional_analysis")
    assert not hasattr(optional_inputs, "planning_evidence_projection")
