import pytest

from google_work_agent.adapters.system.process_runtime_mode import ProcessRuntimeModeAdapter


def test_process_runtime__mode_reconciles__same_operation() -> None:
    adapter = ProcessRuntimeModeAdapter("AUTO")
    assert adapter.set_requested_mode("LOCAL_GPU", "operation-1") == "LOCAL_GPU"

    result = adapter.reconcile_update("operation-1", "LOCAL_GPU")

    assert result.status == "COMPLETED"
    assert result.bounded_result == {"requested_mode": "LOCAL_GPU"}


def test_process_runtime_mode__rejects_operation_ref__reuse_for_another_mode() -> None:
    adapter = ProcessRuntimeModeAdapter("AUTO")
    adapter.set_requested_mode("LOCAL_GPU", "operation-1")

    with pytest.raises(ValueError, match="different runtime mode"):
        adapter.set_requested_mode("API_LLM", "operation-1")


def test_process_runtime_mode__restart_has_no__false_completion_evidence() -> None:
    restarted = ProcessRuntimeModeAdapter("LOCAL_GPU")

    result = restarted.reconcile_update("operation-1", "LOCAL_GPU")

    assert result.status == "SAFE_TO_RETRY"
