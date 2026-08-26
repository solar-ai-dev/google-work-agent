"""Typed same-Run workflow/profile binding contract."""

from dataclasses import dataclass
from typing import Literal

type GraphProfileIdV1 = Literal["SINGLE_BASELINE", "THREE_STAGE", "SIX_ROLE_BASELINE"]


@dataclass(frozen=True, slots=True)
class WorkflowBindingV1:
    schema_version: Literal[1]
    workflow_key: str
    run_id: str
    langgraph_thread_id: str
    graph_profile: GraphProfileIdV1
    graph_version: str
    requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"]
    created_at_ms: int
