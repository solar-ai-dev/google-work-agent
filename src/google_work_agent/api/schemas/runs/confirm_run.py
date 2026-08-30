"""Confirm-run wire request."""

from typing import Literal

from pydantic import model_validator

from google_work_agent.api.schemas.model import ApiModel, ContractVersionedRequest


class ConfirmationResponseV1(ContractVersionedRequest):
    command_id: str
    expected_version: int
    interrupt_id: str
    response_kind: Literal["OPTION", "FREE_TEXT", "DECLINE"]
    selected_option: str | None = None
    free_text: str | None = None

    @model_validator(mode="after")
    def validate_response_choice(self) -> "ConfirmationResponseV1":
        if self.response_kind == "OPTION":
            if not self.selected_option or self.free_text:
                raise ValueError("OPTION requires selected_option and forbids free_text")
        elif self.response_kind == "FREE_TEXT":
            if self.selected_option or not self.free_text or not self.free_text.strip():
                raise ValueError("FREE_TEXT requires text and forbids selected_option")
        elif self.selected_option or self.free_text:
            raise ValueError("DECLINE forbids selected_option and free_text")
        return self


class PendingInterruptResponseV1(ApiModel):
    schema_version: Literal[1] = 1
    interrupt_id: str
    semantic_owner_id: Literal[
        "REQUEST_UNDERSTANDING",
        "TOOL_ROUTE",
        "RETRIEVAL",
        "WORK_ANALYSIS",
        "PLANNING",
        "REVIEW",
    ]
    question: str
    options: list[str]
    response_mode: Literal["OPTION", "FREE_TEXT"]
