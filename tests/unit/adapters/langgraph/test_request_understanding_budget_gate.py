"""G3 RunBudgetV2: proves the budget gate is wired into a real production
node function, not just the isolated helper. request_understanding's
_classify_node is the simplest of the six SIX_ROLE_BASELINE real-LLM-call
nodes (adapters/langgraph/subgraphs/{request_understanding,context_retrieval,
work_analysis,planning,review,tool_routing}.py all follow the same
ensure_llm_call_budget-before / consume_llm_call_budget-after pattern).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast

import pytest

from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.graph import (
    RequestUnderstandingSubgraph,
)
from google_work_agent.application.orchestration.provider_dispatch_budget import (
    account_provider_dispatch,
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    NORMAL_MAX_LLM_CALLS,
    build_default_run_budget,
)
from google_work_agent.ports.llm import (
    LLMErrorCode,
    LLMInvocationError,
    PromptReference,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)

PROMPT_REF = PromptReference(
    prompt_bundle_version="test",
    prompt_id="request_understanding.identify_goal",
    prompt_version="v1",
    content_hash="hash",
    agent_role="request_understanding",
    subgraph_name="request_understanding",
    node_name="identify_goal",
    node_state="INITIAL",
    purpose="test",
    input_schema_version="v1",
    output_schema_version="v1",
)


class _NeverCalledAgent:
    """Fails the test if the Provider boundary is ever reached."""

    def invoke_structured(self, *args: object, **kwargs: object) -> Any:
        raise AssertionError("LLM runtime must not be called once the Run budget is exhausted")


class _FakeLlmResult:
    def __init__(self, *, structured_output_attempts: int) -> None:
        self.structured_output: dict[str, object] = {}
        self.structured_output_attempts = structured_output_attempts


class _RepairingAgent:
    """Simulates one INITIAL call that needed one SCHEMA_REPAIR attempt --
    LLMRuntimeService already folds that into structured_output_attempts=2
    (see application/llm.py's provider_calls_consumed fix)."""

    def __init__(self, *, structured_output_attempts: int) -> None:
        self._structured_output_attempts = structured_output_attempts
        self._llm_runtime = self
        self.calls = 0

    def invoke_structured(self, *args: object, **kwargs: object) -> _FakeLlmResult:
        self.calls += 1
        for _ in range(self._structured_output_attempts):
            account_provider_dispatch()
        result = _FakeLlmResult(structured_output_attempts=self._structured_output_attempts)
        result.structured_output = {
            "goal": "test goal",
            "completion_conditions": ["done"],
            "constraints": [],
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["TASK"],
            "analysis_requirement": "REQUIRED",
        }
        return result


@pytest.fixture(autouse=True)
def _isolate_provider_dispatch_budget() -> Iterator[None]:
    with provider_dispatch_execution_scope():
        yield


def _subgraph(agent: Any = None) -> RequestUnderstandingSubgraph:
    subgraph = object.__new__(RequestUnderstandingSubgraph)
    subgraph._llm_runtime = (  # noqa: SLF001
        agent if agent is not None else cast(Any, _NeverCalledAgent())
    )
    subgraph._identify_goal_prompt_ref = PROMPT_REF  # noqa: SLF001
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
            run_budget=build_default_run_budget(),
            correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
        ),
        "prompt_context": {},
        "run_input": {
            "entry_mode": "AGENT_SEARCH",
            "user_request": "test request",
            "selected_resource_refs": [],
            "requested_mode": "AUTO",
        },
        "trace_context": {
            "agent_node_log": [
                {
                    "agent_subgraph_id": "request_understanding",
                    "agent_invocation_id": "ru-invocation-test",
                }
            ],
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
        subgraph._identify_goal_node(cast(Any, state))  # noqa: SLF001

    assert excinfo.value.code is LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED


def test_a_schema_repair_attempt_consumes_two_llm_calls_not_one() -> None:
    """G3: SCHEMA_REPAIR must also count against llm_calls_used. The node
    consumes provider_calls_consumed==structured_output_attempts, so a call
    that needed one repair attempt (attempts=2) must add 2, not 1."""
    agent = _RepairingAgent(structured_output_attempts=2)
    subgraph = _subgraph(agent)
    state = _state(llm_calls_used=3)

    result = subgraph._identify_goal_node(cast(Any, state))  # noqa: SLF001

    assert agent.calls == 1
    assert cast(dict[str, Any], result["retry_budget"])["llm_calls_used"] == 5
