"""Get-run-context wire response."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class RunContextBudgetV2(ApiModel):
    schema_version: Literal[2]
    profile: Literal["NORMAL", "RETRIEVAL_HEAVY", "REVISION_HEAVY"]
    started_at_ms: int
    max_execution_ms: int
    llm_calls_used: int
    llm_call_limit: int
    connector_calls_used: int
    max_connector_calls: int
    source_page_calls_used: int
    max_source_page_calls: int
    detail_fetches_used: int
    max_detail_fetches: int
    context_tokens_used: int
    max_context_tokens: int
    retry_attempts_used: int
    max_retry_attempts: int
    absolute_llm_call_limit: Literal[24]
    schema_repairs_used_by_node: dict[str, int]
    semantic_revisions_used_by_failure: dict[str, int]
    planning_revisions_used: int
    review_rechecks_used: int
    additional_retrieval_rounds_used: int


class SelectedResourceResponse(ApiModel):
    source: str
    resource_type: str
    resource_id: str
    parent_resource_id: str | None


class ExecutionContextResponse(ApiModel):
    run_id: str
    conversation_id: str
    workflow_key: str
    entry_mode: str
    requested_mode: str
    status: str
    version: int
    request_text: str
    selected_resource_ids: list[str]
    run_budget: RunContextBudgetV2
    selected_resources: list[SelectedResourceResponse]


class RunContextResponse(ApiModel):
    context: ExecutionContextResponse | None
    api_contract_version: str


__all__ = [
    "ExecutionContextResponse",
    "RunContextBudgetV2",
    "RunContextResponse",
    "SelectedResourceResponse",
]
