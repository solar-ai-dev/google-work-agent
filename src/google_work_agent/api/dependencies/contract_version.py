"""Validate the versioned Local API wire contract."""

from google_work_agent.api.errors.api_request_error import ApiRequestError


def enforce_supported_api_contract_version(
    *,
    supported_version: str,
    request_id: str,
    request_version: str | None,
) -> None:
    if request_version is None:
        return
    if request_version != supported_version:
        raise ApiRequestError(
            error_code="VERSION_CONFLICT",
            user_message="지원하지 않는 API 계약 버전입니다.",
            status_code=409,
            request_id=request_id,
            detail_code="API_CONTRACT_VERSION_MISMATCH",
        )
