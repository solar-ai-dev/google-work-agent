from google_work_agent.api.errors.result_code_http_mapping import (
    error_code_for_result_code,
    http_status_for_result_code,
)
from google_work_agent.domain.results import ResultCode


def test_result_codes__map_to_the__documented_http_status() -> None:
    assert http_status_for_result_code(ResultCode.TRANSITION_APPLIED.value) == 200
    assert http_status_for_result_code(ResultCode.VERSION_CONFLICT.value) == 409
    assert http_status_for_result_code(ResultCode.DUPLICATE_COMMAND.value) == 409
    assert http_status_for_result_code(ResultCode.STATE_CONFLICT.value) == 409
    assert http_status_for_result_code(ResultCode.RECOVERY_REQUIRED.value) == 409
    # arguments_patch fields the Tool Registry does not allow are a schema
    # precondition violation, not a version/state conflict -- 07-tool-mcp-
    # internal-interface.md section 3.3 puts these in the 422 class.
    assert http_status_for_result_code(ResultCode.SCHEMA_VIOLATION.value) == 422


def test_schema_violation__maps_to_a__named_error_code() -> None:
    assert error_code_for_result_code(ResultCode.SCHEMA_VIOLATION.value) == "SCHEMA_VIOLATION"
