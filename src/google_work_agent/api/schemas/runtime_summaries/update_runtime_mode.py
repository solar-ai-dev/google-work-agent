"""Runtime requested-mode command wire contract."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel
from google_work_agent.api.schemas.runtime_summaries.get_runtime_summary import RuntimeModeStatus


class UpdateRuntimeModeRequest(ApiModel):
    command_id: str
    requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"]


__all__ = ["RuntimeModeStatus", "UpdateRuntimeModeRequest"]
