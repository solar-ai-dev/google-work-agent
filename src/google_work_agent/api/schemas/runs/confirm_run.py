"""Confirm-run wire request."""

from typing import Literal

from pydantic import Field, model_validator

from google_work_agent.api.schemas.common import ContractVersionedRequest


class ConfirmationResponseV1(ContractVersionedRequest):
    command_id: str
    expected_version: int
    interrupt_id: str
    response_kind: Literal["OPTION_SELECTION", "FREE_TEXT"]
    selected_option_ids: list[str] = Field(default_factory=list)
    free_text: str | None = None

    @model_validator(mode="after")
    def validate_response_choice(self) -> "ConfirmationResponseV1":
        if self.response_kind == "OPTION_SELECTION":
            if not self.selected_option_ids or self.free_text:
                raise ValueError("OPTION_SELECTION requires options and forbids free_text")
        elif self.selected_option_ids or not self.free_text or not self.free_text.strip():
            raise ValueError("FREE_TEXT requires text and forbids selected options")
        return self
