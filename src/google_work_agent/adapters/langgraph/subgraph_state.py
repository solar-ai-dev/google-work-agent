"""Shared runtime-only contracts for native agent subgraphs."""

from __future__ import annotations

from typing import Literal, Required, TypedDict

from google_work_agent.application.prompt_runtime.contracts.provider_dispatch import (
    AgentDispositionV1,
    AgentFailureRecordV1,
    PromptRef,
)
from google_work_agent.application.use_cases.run.guard_run_budget import RunBudgetV2
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest


class AgentLocalStateV1(TypedDict):
    """Canonical invocation-local state shared by native agent kernels."""

    schema_version: Required[Literal[1]]
    agent_role: str
    invocation_id: str
    node_state: str
    input_projection: dict[str, object]
    candidate_output: dict[str, object] | None
    prompt_ref: PromptRef | None
    attempt_no: int
    schema_repair_count: int
    semantic_revision_count: int
    failure_record: AgentFailureRecordV1 | None
    disposition: AgentDispositionV1 | None
    typed_result: dict[str, object] | None


AGENT_LOCAL_STATE_FIELDS = frozenset(AgentLocalStateV1.__annotations__)


class AgentSubgraphInputEnvelope(TypedDict, total=False):
    """Correlation and control envelope shared by every agent subgraph."""

    schema_version: int
    run_id: str
    conversation_id: str
    thread_id: str
    workflow_phase: str
    retry_budget: RunBudgetV2
    prompt_context: dict[str, object]
    trace_context: dict[str, object]
    __request__: WorkflowStartRequest
    __target__: str
    __logical_target__: str
    __workflow_control__: dict[str, object] | None


__all__ = [
    "AGENT_LOCAL_STATE_FIELDS",
    "AgentLocalStateV1",
    "AgentSubgraphInputEnvelope",
]
