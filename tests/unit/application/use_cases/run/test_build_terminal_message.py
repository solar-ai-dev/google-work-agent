"""Canonical terminal-message contract and deterministic formatting proof."""

import pytest

from google_work_agent.application.use_cases.run.build_terminal_message import (
    BuildTerminalMessageHandler,
    BuildTerminalMessageQueryV1,
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
