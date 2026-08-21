"""Cancel-run wire request and common run command response."""

from google_work_agent.api.schemas.common import ApiModel, ContractVersionedRequest


class CancelRunRequestV2(ContractVersionedRequest):
    command_id: str
    expected_run_version: int


class RunCommandResponse(ApiModel):
    applied: bool
    result_code: str
    run_id: str
    run_status: str
    run_version: int
    should_enqueue: bool | None = None
    request_replayed: bool | None = None
    conflict_detail: str | None = None
    result_kind: str | None = None
