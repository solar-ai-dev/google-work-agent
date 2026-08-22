"""Structured Local API request error."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ApiRequestError(Exception):
    error_code: str
    user_message: str
    status_code: int
    request_id: str
    retryable: bool = False
    current_state: str | None = None
    detail_code: str | None = None
