"""G3 RunBudgetV1: proves the budget gate is wired into a real production
node function, not just the isolated helper. request_understanding's
_classify_node is the simplest of the six SIX_ROLE_BASELINE real-LLM-call
nodes (adapters/langgraph/subgraphs/{request_understanding,context_retrieval,
work_analysis,planning,review,tool_routing}.py all follow the same
ensure_llm_call_budget-before / consume_llm_call_budget-after pattern).
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from google_work_agent.adapters.langgraph.graph_state import REQUEST_AGENT_LOCAL_KEY
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.request_understanding import (
    RequestUnderstandingSubgraph,
)
from google_work_agent.application.workflows import NORMAL_MAX_LLM_CALLS, build_default_run_budget
from google_work_agent.ports import (
    LLMErrorCode,
    LLMInvocationError,
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


class _NeverCalledAgent:
    """Fails the test if the Provider boundary is ever reached."""

    prompt_ref = None

    def invoke_classify_llm(self, *args: object, **kwargs: object) -> Any:
        raise AssertionError(
            "invoke_classify_llm must not be called once the Run LLM budget is exhausted"
        )


class _FakeLlmResult:
    def __init__(self, *, structured_output_attempts: int) -> None:
        self.structured_output: dict[str, object] = {}
        self.structured_output_attempts = structured_output_attempts


class _RepairingAgent:
    """Simulates one INITIAL call that needed one SCHEMA_REPAIR attempt --
    LLMRuntimeService already folds that into structured_output_attempts=2
    (see application/llm.py's provider_calls_consumed fix)."""

    prompt_ref = None

    def __init__(self, *, structured_output_attempts: int) -> None:
        self._structured_output_attempts = structured_output_attempts
        self.calls = 0

    def invoke_classify_llm(self, *args: object, **kwargs: object) -> _FakeLlmResult:
        self.calls += 1
        return _FakeLlmResult(structured_output_attempts=self._structured_output_attempts)

    def build_output_from_llm_result(self, llm_result: _FakeLlmResult) -> dict[str, object]:
        del llm_result
        return {
            "schema_version": 1,
            "result": "COMPLETE",
            "request_intent": None,
            "clarification": None,
            "failure": None,
            "validator_codes": [],
            "llm_provider_result": {},
        }


def _subgraph(agent: Any = None) -> RequestUnderstandingSubgraph:
    subgraph = object.__new__(RequestUnderstandingSubgraph)
    subgraph._agent = agent if agent is not None else cast(Any, _NeverCalledAgent())  # noqa: SLF001
    subgraph._graph_profile = GraphProfile.SIX_ROLE_BASELINE  # noqa: SLF001
    return subgraph


def _state(*, llm_calls_used: int) -> dict[str, object]:
    return {
        "run_id": "run-1",
        "__request__": WorkflowStartRequest(
            run_id="run-1",
            conversation_id="conversation-1",
            workflow_key="thread-1",
            entry_mode="AGENT_SEARCH",
            requested_mode="AUTO",
            request_text="test request",
            selected_resource_ids=(),
            correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
        ),
        "prompt_context": {},
        REQUEST_AGENT_LOCAL_KEY: {
            "schema_version": 1,
            "agent_role": "request_understanding",
            "invocation_id": "invocation-1",
            "node_state": "INITIALIZED",
            "input_projection": {},
            "candidate_output": None,
            "prompt_ref": None,
            "attempt_no": 1,
            "schema_repair_count": 0,
            "semantic_revision_count": 0,
            "failure_record": None,
            "disposition": None,
            "typed_result": None,
        },
        "retry_budget": {
            **build_default_run_budget(),
            "llm_calls_used": llm_calls_used,
        },
    }


def test_exhausted_budget_blocks_the_call_before_the_agent_is_ever_invoked() -> None:
    subgraph = _subgraph()
    state = _state(llm_calls_used=NORMAL_MAX_LLM_CALLS)

    with pytest.raises(LLMInvocationError) as excinfo:
        subgraph._classify_node(cast(Any, state))  # noqa: SLF001

    assert excinfo.value.code is LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED


def test_a_schema_repair_attempt_consumes_two_llm_calls_not_one() -> None:
    """G3: SCHEMA_REPAIR must also count against llm_calls_used. The node
    consumes provider_calls_consumed==structured_output_attempts, so a call
    that needed one repair attempt (attempts=2) must add 2, not 1."""
    agent = _RepairingAgent(structured_output_attempts=2)
    subgraph = _subgraph(agent)
    state = _state(llm_calls_used=3)

    result = subgraph._classify_node(cast(Any, state))  # noqa: SLF001

    assert agent.calls == 1
    assert cast(dict[str, Any], result["retry_budget"])["llm_calls_used"] == 5
