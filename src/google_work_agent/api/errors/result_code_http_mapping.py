"""Map Application result codes to Local API HTTP outcomes."""

from google_work_agent.domain.results import ResultCode


def http_status_for_result_code(result_code: str, *, default_success: int = 200) -> int:
    code = ResultCode(result_code) if result_code in ResultCode._value2member_map_ else None
    if code in {
        ResultCode.VERSION_CONFLICT,
        ResultCode.DUPLICATE_COMMAND,
        ResultCode.STATE_CONFLICT,
        ResultCode.RECOVERY_REQUIRED,
    }:
        return 409
    if code is ResultCode.SCHEMA_VIOLATION:
        return 422
    return default_success


def error_code_for_result_code(result_code: str) -> str:
    mapping = {
        ResultCode.VERSION_CONFLICT.value: "VERSION_CONFLICT",
        ResultCode.DUPLICATE_COMMAND.value: "DUPLICATE_COMMAND",
        ResultCode.STATE_CONFLICT.value: "STATE_CONFLICT",
        ResultCode.RECOVERY_REQUIRED.value: "RECOVERY_REQUIRED",
        ResultCode.SCHEMA_VIOLATION.value: "SCHEMA_VIOLATION",
    }
    return mapping.get(result_code, "INTERNAL_ERROR")
