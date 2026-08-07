"""Shared API schemas."""

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorEnvelope(ApiModel):
    error_code: str
    user_message: str
    retryable: bool
    request_id: str
    api_contract_version: str
    current_state: str | None = None
    detail_code: str | None = None


class ContractVersionedRequest(ApiModel):
    api_contract_version: str
