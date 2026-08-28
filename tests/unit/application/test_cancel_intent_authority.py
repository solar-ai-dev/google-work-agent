from google_work_agent.application.use_cases.run.cancel_intent import (
    has_durable_cancel_intent,
    is_applied_request_cancel_receipt,
)


class _Reader:
    def __init__(self, value: bool) -> None:
        self.value = value
        self.calls: list[str] = []

    def has_durable_intent(self, run_id: str) -> bool:
        self.calls.append(run_id)
        return self.value


def test_only_applied_request_cancel_receipt_is_cancel_authority() -> None:
    assert is_applied_request_cancel_receipt(
        command_type="RequestRunCancellation",
        aggregate_type="Run",
        aggregate_id="run-1",
        status="APPLIED",
        result_code="TRANSITION_APPLIED",
        run_id="run-1",
    )

    for changed in (
        {"command_type": "FinalizeRunCancellation"},
        {"aggregate_type": "Audit"},
        {"aggregate_id": "run-2"},
        {"status": "REJECTED"},
        {"result_code": "STATE_CONFLICT"},
    ):
        values = {
            "command_type": "RequestRunCancellation",
            "aggregate_type": "Run",
            "aggregate_id": "run-1",
            "status": "APPLIED",
            "result_code": "TRANSITION_APPLIED",
            "run_id": "run-1",
            **changed,
        }
        assert not is_applied_request_cancel_receipt(**values)


def test_cancel_query_delegates_to_receipt_reader_not_audit() -> None:
    reader = _Reader(True)

    assert has_durable_cancel_intent(reader, "run-1") is True
    assert reader.calls == ["run-1"]
