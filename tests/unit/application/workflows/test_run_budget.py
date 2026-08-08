import pytest

from google_work_agent.application.workflows import (
    ABSOLUTE_MAX_LLM_CALLS,
    MAX_ADDITIONAL_ACQUISITIONS,
    NORMAL_MAX_LLM_CALLS,
    PLANNING_REVISION_PER_RUN,
    RETRIEVAL_HEAVY_MAX_LLM_CALLS,
    REVISION_HEAVY_MAX_LLM_CALLS,
    BudgetDecision,
    BudgetProfile,
    BudgetReasonCode,
    approve_additional_acquisition,
    approve_planning_revision,
    approve_review_recheck,
    approve_semantic_revision,
    build_default_run_budget,
    build_semantic_failure_signature_v1,
    check_llm_call_budget,
    consume_llm_provider_calls,
    promote_budget_profile,
    validate_run_budget_v1,
)


def test_default_run_budget_is_valid_and_checkpoint_safe() -> None:
    budget = validate_run_budget_v1(build_default_run_budget())

    assert budget == {
        "schema_version": 1,
        "profile": BudgetProfile.NORMAL.value,
        "llm_calls_used": 0,
        "additional_acquisitions_used": 0,
        "planning_revisions_used": 0,
        "last_rechecked_planning_revision": 0,
        "semantic_revision_signatures_used": [],
    }


def test_run_budget_validator_rejects_invalid_counters_profile_and_duplicates() -> None:
    with pytest.raises(ValueError, match="run budget llm_calls_used must be non-negative"):
        validate_run_budget_v1(
            {
                **build_default_run_budget(),
                "llm_calls_used": -1,
            }
        )

    with pytest.raises(ValueError, match="run budget additional_acquisitions_used exceeds"):
        validate_run_budget_v1(
            {
                **build_default_run_budget(),
                "additional_acquisitions_used": MAX_ADDITIONAL_ACQUISITIONS + 1,
            }
        )

    with pytest.raises(ValueError, match="run budget planning_revisions_used exceeds"):
        validate_run_budget_v1(
            {
                **build_default_run_budget(),
                "planning_revisions_used": PLANNING_REVISION_PER_RUN + 1,
            }
        )

    with pytest.raises(
        ValueError,
        match="last_rechecked_planning_revision must be less than or equal",
    ):
        validate_run_budget_v1(
            {
                **build_default_run_budget(),
                "planning_revisions_used": 1,
                "last_rechecked_planning_revision": 2,
            }
        )

    with pytest.raises(ValueError, match="run budget profile is invalid"):
        validate_run_budget_v1(
            {
                **build_default_run_budget(),
                "profile": "ABSOLUTE",
            }
        )

    signature = build_semantic_failure_signature_v1(
        node_id="review.inspect",
        failure_reason_codes=["PLAN_REQUIRED_ACTION_MISSING"],
    )
    with pytest.raises(
        ValueError,
        match="run budget semantic_revision_signatures_used contains duplicates",
    ):
        validate_run_budget_v1(
            {
                **build_default_run_budget(),
                "semantic_revision_signatures_used": [signature, signature],
            }
        )


def test_semantic_failure_signature_is_canonicalized_by_node_and_reason_set() -> None:
    first = build_semantic_failure_signature_v1(
        node_id="review.inspect",
        failure_reason_codes=["B", "A", "B"],
    )
    second = build_semantic_failure_signature_v1(
        node_id="review.inspect",
        failure_reason_codes=["A", "B"],
    )
    third = build_semantic_failure_signature_v1(
        node_id="planning.revise_answer",
        failure_reason_codes=["A", "B"],
    )

    assert first == second
    assert first["failure_reason_codes"] == ["A", "B"]
    assert first != third


def test_profile_promotion_is_monotonic_and_has_no_absolute_profile() -> None:
    assert (
        promote_budget_profile(BudgetProfile.NORMAL, BudgetProfile.REVISION_HEAVY)
        is BudgetProfile.REVISION_HEAVY
    )
    assert (
        promote_budget_profile(BudgetProfile.NORMAL, BudgetProfile.RETRIEVAL_HEAVY)
        is BudgetProfile.RETRIEVAL_HEAVY
    )
    assert (
        promote_budget_profile(BudgetProfile.REVISION_HEAVY, BudgetProfile.RETRIEVAL_HEAVY)
        is BudgetProfile.RETRIEVAL_HEAVY
    )
    assert (
        promote_budget_profile(BudgetProfile.RETRIEVAL_HEAVY, BudgetProfile.REVISION_HEAVY)
        is BudgetProfile.RETRIEVAL_HEAVY
    )


def test_llm_budget_gate_and_accounting_follow_profile_and_absolute_limits() -> None:
    budget = {
        **build_default_run_budget(),
        "llm_calls_used": NORMAL_MAX_LLM_CALLS - 1,
    }
    allow = check_llm_call_budget(budget)
    consumed = consume_llm_provider_calls(allow["run_budget"])

    assert allow["decision"] == BudgetDecision.ALLOW.value
    assert consumed["llm_calls_used"] == NORMAL_MAX_LLM_CALLS

    deny_profile = check_llm_call_budget(consumed)
    assert deny_profile["decision"] == BudgetDecision.DENY.value
    assert deny_profile["budget_reason_code"] == BudgetReasonCode.PROFILE_LLM_LIMIT_EXHAUSTED.value

    absolute_budget = {
        **build_default_run_budget(),
        "profile": BudgetProfile.RETRIEVAL_HEAVY.value,
        "llm_calls_used": ABSOLUTE_MAX_LLM_CALLS,
    }
    deny_absolute = check_llm_call_budget(absolute_budget)
    assert deny_absolute["decision"] == BudgetDecision.DENY.value
    assert (
        deny_absolute["budget_reason_code"] == BudgetReasonCode.ABSOLUTE_LLM_LIMIT_EXHAUSTED.value
    )


def test_additional_acquisition_counter_promotes_profile_and_denies_third_round() -> None:
    first = approve_additional_acquisition(build_default_run_budget())
    second = approve_additional_acquisition(first["run_budget"])
    third = approve_additional_acquisition(second["run_budget"])

    assert first["decision"] == BudgetDecision.ALLOW.value
    assert first["run_budget"]["additional_acquisitions_used"] == 1
    assert first["run_budget"]["profile"] == BudgetProfile.RETRIEVAL_HEAVY.value

    assert second["decision"] == BudgetDecision.ALLOW.value
    assert second["run_budget"]["additional_acquisitions_used"] == 2
    assert second["run_budget"]["profile"] == BudgetProfile.RETRIEVAL_HEAVY.value

    assert third["decision"] == BudgetDecision.DENY.value
    assert (
        third["budget_reason_code"] == BudgetReasonCode.ADDITIONAL_ACQUISITION_LIMIT_EXHAUSTED.value
    )


def test_planning_revision_counter_is_shared_by_answer_and_plan_revisions() -> None:
    answer_revision = approve_planning_revision(build_default_run_budget())
    plan_revision = approve_planning_revision(answer_revision["run_budget"])
    third_revision = approve_planning_revision(plan_revision["run_budget"])

    assert answer_revision["decision"] == BudgetDecision.ALLOW.value
    assert answer_revision["run_budget"]["planning_revisions_used"] == 1
    assert answer_revision["run_budget"]["profile"] == BudgetProfile.REVISION_HEAVY.value

    assert plan_revision["decision"] == BudgetDecision.ALLOW.value
    assert plan_revision["run_budget"]["planning_revisions_used"] == 2
    assert plan_revision["run_budget"]["profile"] == BudgetProfile.REVISION_HEAVY.value

    assert third_revision["decision"] == BudgetDecision.DENY.value
    assert (
        third_revision["budget_reason_code"]
        == BudgetReasonCode.PLANNING_REVISION_LIMIT_EXHAUSTED.value
    )


def test_review_recheck_requires_revision_and_allows_once_per_revision() -> None:
    no_revision = approve_review_recheck(build_default_run_budget())
    first_revision = approve_planning_revision(build_default_run_budget())
    first_recheck = approve_review_recheck(first_revision["run_budget"])
    second_recheck = approve_review_recheck(first_recheck["run_budget"])
    second_revision = approve_planning_revision(first_recheck["run_budget"])
    recheck_after_second_revision = approve_review_recheck(second_revision["run_budget"])

    assert no_revision["decision"] == BudgetDecision.DENY.value
    assert (
        no_revision["budget_reason_code"] == BudgetReasonCode.REVIEW_RECHECK_LIMIT_EXHAUSTED.value
    )

    assert first_recheck["decision"] == BudgetDecision.ALLOW.value
    assert first_recheck["run_budget"]["last_rechecked_planning_revision"] == 1

    assert second_recheck["decision"] == BudgetDecision.DENY.value
    assert (
        second_recheck["budget_reason_code"]
        == BudgetReasonCode.REVIEW_RECHECK_LIMIT_EXHAUSTED.value
    )

    assert second_revision["run_budget"]["planning_revisions_used"] == 2
    assert recheck_after_second_revision["decision"] == BudgetDecision.ALLOW.value
    assert recheck_after_second_revision["run_budget"]["last_rechecked_planning_revision"] == 2


def test_semantic_same_failure_gate_denies_same_node_and_reason_set_only() -> None:
    signature = build_semantic_failure_signature_v1(
        node_id="review.inspect",
        failure_reason_codes=["PLAN_REQUIRED_ACTION_MISSING", "EVIDENCE_SUPPORTED"],
    )
    same_signature_different_order = build_semantic_failure_signature_v1(
        node_id="review.inspect",
        failure_reason_codes=["EVIDENCE_SUPPORTED", "PLAN_REQUIRED_ACTION_MISSING"],
    )
    different_node = build_semantic_failure_signature_v1(
        node_id="planning.revise_answer",
        failure_reason_codes=["PLAN_REQUIRED_ACTION_MISSING", "EVIDENCE_SUPPORTED"],
    )

    first = approve_semantic_revision(build_default_run_budget(), signature=signature)
    same = approve_semantic_revision(first["run_budget"], signature=same_signature_different_order)
    different = approve_semantic_revision(first["run_budget"], signature=different_node)

    assert first["decision"] == BudgetDecision.ALLOW.value
    assert len(first["run_budget"]["semantic_revision_signatures_used"]) == 1

    assert same["decision"] == BudgetDecision.DENY.value
    assert (
        same["budget_reason_code"] == BudgetReasonCode.SEMANTIC_SAME_FAILURE_LIMIT_EXHAUSTED.value
    )

    assert different["decision"] == BudgetDecision.ALLOW.value
    assert len(different["run_budget"]["semantic_revision_signatures_used"]) == 2


def test_budget_profile_constants_match_frozen_contract() -> None:
    assert NORMAL_MAX_LLM_CALLS == 8
    assert REVISION_HEAVY_MAX_LLM_CALLS == 12
    assert RETRIEVAL_HEAVY_MAX_LLM_CALLS == 14
    assert ABSOLUTE_MAX_LLM_CALLS == 16
