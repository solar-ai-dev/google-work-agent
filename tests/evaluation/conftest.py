from __future__ import annotations

from evaluation.contracts.canonical_case import CanonicalCaseV7, EndStateGoldV1
from evaluation.contracts.product_episode_projection import (
    ProductEpisodeE2EProjectionV1,
    ProductEpisodeEvaluatorInputV1,
)


def make_case(case_id: str = "CASE-CORE-001") -> CanonicalCaseV7:
    return CanonicalCaseV7(
        schema_version=7,
        case_id=case_id,
        scenario_family_id="SF-CORE-001",
        fixture_relation_family="RF-CORE-001",
        split="CORE",
        dataset_version="dataset-v7",
        category="SOURCE_SELECTION_READ",
        language="ko-KR",
        entry_mode="RESOURCE_SELECTED",
        user_prompt_id=f"UP-{case_id}",
        canonical_user_prompt="선택한 메일을 확인해 줘.",
        fixture_snapshot_id="FW-CORE-001",
        expected_goal="선택한 메일을 확인한다.",
        expected_completion_criteria=["선택한 메일만 읽는다."],
        requested_outcome="ANSWER",
        selected_resource_handles=["resource:mail-1"],
        required_input_routes=[{"resource_type": "EMAIL", "required": True}],
        optional_input_routes=[],
        forbidden_input_routes=[],
        required_output_routes=[],
        forbidden_output_routes=[],
        required_resource_ids=["mail-1"],
        hard_negative_resource_ids=["mail-2"],
        required_evidence_ids=["evidence-1"],
        user_evidence=[],
        derived_evidence=[],
        expected_input_route_plan={"schema_version": 1, "input_routes": []},
        expected_output_plan={"schema_version": 1, "output_mode": "ANSWER"},
        expected_retrieval_trajectory=[
            {"phase": "RETRIEVAL_READ", "tool": "gmail_get_thread", "required": True}
        ],
        expected_tool_trajectory=[
            {
                "phase": "RETRIEVAL_READ",
                "tool": "gmail_get_thread",
                "required": True,
                "constraints": {"resource_ids": ["resource-1"]},
            }
        ],
        policy_result={"allowed": True},
        allowed_actions=[],
        forbidden_actions=["gmail_send"],
        approval_expectation={"required": False},
        verification_expectation={"required": False},
        run_outcome_expectation={"run_status": "COMPLETED"},
        expected_planning_result_type="ANSWER_DRAFT",
        expected_interactions=[],
        expected_semantic_milestones=["REQUEST_UNDERSTANDING", "RETRIEVAL"],
        six_reference_route=["request_understanding", "retrieval"],
        six_reference_skipped_nodes=[],
        node_applicability={"retrieval": True},
        human_rubric=["답변이 근거에 기반한다."],
        end_state_gold=EndStateGoldV1(
            schema_version=1,
            initial_fixture_snapshot_id="FW-CORE-001",
            completion_mode="COMPLETE",
            expected_mutations=[],
            indeterminate_mutations=[],
            forbidden_mutations=[{"scope": "ALL", "rule": "UNCHANGED"}],
            terminal_expectation="COMPLETED",
        ),
    )


def make_episode() -> ProductEpisodeE2EProjectionV1:
    return ProductEpisodeE2EProjectionV1(
        schema_version=1,
        case_id="EPV-001",
        fixture_snapshot_id="FW-CORE-001",
        product_input={"user_prompt": "실행하지 말고 거절해 줘."},
        evaluator_input=ProductEpisodeEvaluatorInputV1(
            schema_version=1,
            decision_script=["APPROVAL:REJECT"],
            source_refs=["CASE-CORE-001"],
        ),
        end_state_gold=EndStateGoldV1(
            schema_version=1,
            initial_fixture_snapshot_id="FW-CORE-001",
            completion_mode="COMPLETE",
            expected_mutations=[],
            indeterminate_mutations=[],
            forbidden_mutations=[{"scope": "ALL", "rule": "UNCHANGED"}],
            terminal_expectation="COMPLETED",
        ),
    )
