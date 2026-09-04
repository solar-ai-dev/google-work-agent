"""Canonical terminal-message contract and deterministic formatting proof."""

import pytest

from google_work_agent.application.use_cases.run.build_terminal_message import (
    BuildTerminalMessageHandler,
    BuildTerminalMessageQueryV1,
    TerminalActionOutcomeV1,
    TerminalMessageSourceKindV1,
    TerminalResultKindV1,
)


def test_answer_draft_is__preserved_by_the__exact_v1_contract() -> None:
    result = BuildTerminalMessageHandler()(
        BuildTerminalMessageQueryV1(
            schema_version=1,
            run_id="run-1",
            expected_run_version=3,
            source_kind="ANSWER_DRAFT",
            result_kind="PARTIAL",
            answer_text="  bounded answer  ",
            reason_codes=["BOUNDED_INSUFFICIENCY"],
        )
    )

    assert result.schema_version == 1
    assert result.result_kind == "PARTIAL"
    assert result.content == "  bounded answer  "
    assert result.reason_codes == ["BOUNDED_INSUFFICIENCY"]


def test_verified_write__uses_request_language_and__durable_action_result() -> None:
    result = BuildTerminalMessageHandler()(
        BuildTerminalMessageQueryV1(
            schema_version=1,
            run_id="run-1",
            expected_run_version=3,
            source_kind="WRITE_VERIFICATION_SUMMARY",
            result_kind="SUCCESS",
            answer_text=None,
            reason_codes=["WRITE_VERIFIED"],
            request_text="분기 보고서 검토 태스크를 만들어 줘",
            action_outcomes=(
                TerminalActionOutcomeV1(
                    tool_name="tasks_create_task",
                    effect_type="CREATE",
                    status="VERIFIED",
                    arguments={"payload": {"title": "분기 보고서 검토"}},
                ),
            ),
        )
    )

    assert "분기 보고서 검토" in result.content
    assert "Google에서 결과를 다시 확인했습니다" in result.content
    assert "WRITE_VERIFIED" not in result.content
    assert "completed successfully" not in result.content


def test_verified_read__includes_durable__evidence_excerpt() -> None:
    result = BuildTerminalMessageHandler()(
        BuildTerminalMessageQueryV1(
            schema_version=1,
            run_id="run-1",
            expected_run_version=3,
            source_kind="READ_RESULT_SUMMARY",
            result_kind="SUCCESS",
            answer_text=None,
            reason_codes=[],
            request_text="선택한 메일을 요약해 줘",
            action_outcomes=(
                TerminalActionOutcomeV1(
                    tool_name="gmail_get_thread",
                    effect_type="READ",
                    status="VERIFIED",
                    arguments={"thread_id": "thread-project"},
                    evidence_excerpts=("목요일 회고 초안이 필요합니다.",),
                ),
            ),
        )
    )

    assert "목요일 회고 초안이 필요합니다" in result.content
    assert "자료를 읽고 답변에 반영했습니다" not in result.content


def test_partial_write__distinguishes_completed__and_unfinished_actions() -> None:
    result = BuildTerminalMessageHandler()(
        BuildTerminalMessageQueryV1(
            1,
            "run-1",
            4,
            "WRITE_VERIFICATION_SUMMARY",
            "PARTIAL",
            None,
            ["WRITE_CLOSED"],
            "Create the approved tasks",
            (
                TerminalActionOutcomeV1(
                    "tasks_create_task", "CREATE", "VERIFIED", {"title": "Send report"}
                ),
                TerminalActionOutcomeV1(
                    "tasks_create_task", "CREATE", "CANCELLED", {"title": "Book room"}
                ),
            ),
        )
    )

    assert result.content.startswith("I could complete only part of your request.")
    assert "Send report" in result.content and "Created and verified" in result.content
    assert "Book room" in result.content and "Cancelled before completion" in result.content
    assert "WRITE_CLOSED" not in result.content


def test_blocked_result__does_not_expose__reason_code() -> None:
    result = BuildTerminalMessageHandler()(
        BuildTerminalMessageQueryV1(
            1,
            "run-1",
            1,
            "POLICY_BLOCK",
            "BLOCKED",
            None,
            ["PLAN_REVIEW_BLOCK"],
            "이 요청을 처리해 줘",
        )
    )

    assert "안전 정책" in result.content
    assert "PLAN_REVIEW_BLOCK" not in result.content


def test_context_block__explains_missing_source_and_next_action() -> None:
    result = BuildTerminalMessageHandler()(
        BuildTerminalMessageQueryV1(
            1,
            "run-1",
            1,
            "POLICY_BLOCK",
            "BLOCKED",
            None,
            ["CONTEXT_BLOCKED"],
            "Gmail에서 회의 관련 메일을 찾아줘",
        )
    )

    assert "일치하는 Google 자료를 찾지 못해" in result.content
    assert "검색 조건을 바꾸거나" in result.content
    assert "Google 변경은 실행하지 않았습니다" in result.content
    assert "CONTEXT_BLOCKED" not in result.content


@pytest.mark.parametrize(
    ("source_kind", "result_kind", "reason_code", "expected"),
    (
        ("RECOVERY_RESULT", "FAILED", "RECOVERY_FAIL", "성공으로 처리하지 않았습니다"),
        ("CANCEL_RESULT", "CANCELLED", "CANCEL_REQUESTED", "취소했습니다"),
    ),
)
def test_failed_and_cancelled_results__use_request_language__without_raw_codes(
    source_kind: TerminalMessageSourceKindV1,
    result_kind: TerminalResultKindV1,
    reason_code: str,
    expected: str,
) -> None:
    result = BuildTerminalMessageHandler()(
        BuildTerminalMessageQueryV1(
            1,
            "run-1",
            2,
            source_kind,
            result_kind,
            None,
            [reason_code],
            "회의 준비 작업을 처리해 줘",
        )
    )

    assert expected in result.content
    assert reason_code not in result.content


@pytest.mark.parametrize(
    ("query", "message"),
    (
        (
            BuildTerminalMessageQueryV1(1, "run-1", 0, "ANSWER_DRAFT", "SUCCESS", None, []),
            "ANSWER_DRAFT requires",
        ),
        (
            BuildTerminalMessageQueryV1(
                1, "run-1", 0, "CANCEL_RESULT", "CANCELLED", "not allowed", []
            ),
            "only allowed",
        ),
        (
            BuildTerminalMessageQueryV1(
                1, "run-1", 0, "RECOVERY_RESULT", "FAILED", None, ["x" * 65]
            ),
            "1..64",
        ),
    ),
)
def test_exact_v1__contract_rejects__invalid_inputs(
    query: BuildTerminalMessageQueryV1, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        BuildTerminalMessageHandler()(query)
