"""Start-run wire contracts."""

from typing import Literal

from pydantic import Field, model_validator

from google_work_agent.api.schemas.model import ApiModel, ContractVersionedRequest


class StartRunRequest(ContractVersionedRequest):
    command_id: str
    conversation_id: str
    request_text: str
    entry_mode: Literal["AGENT_SEARCH", "RESOURCE_SELECTED"]
    selected_resource_handles: list[str] = Field(default_factory=list, max_length=20)
    requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"]

    @model_validator(mode="after")
    def validate_selection_mode(self) -> "StartRunRequest":
        unique_handles = set(self.selected_resource_handles)
        if len(unique_handles) != len(self.selected_resource_handles):
            raise ValueError("selected_resource_handles must be unique")
        if self.entry_mode == "AGENT_SEARCH" and self.selected_resource_handles:
            raise ValueError("AGENT_SEARCH cannot include selected resources")
        if self.entry_mode == "RESOURCE_SELECTED" and not self.selected_resource_handles:
            raise ValueError("RESOURCE_SELECTED requires at least one selection handle")
        return self


class StartRunResponseV1(ApiModel):
    run_id: str
    conversation_id: str
    langgraph_thread_id: str
    status: str
    version: int
    event_stream_url: str


__all__ = ["StartRunRequest", "StartRunResponseV1"]
