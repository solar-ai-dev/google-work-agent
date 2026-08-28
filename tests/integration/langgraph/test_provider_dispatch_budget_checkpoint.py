from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.agent_kernel import (
    consume_llm_call_budget,
    ensure_llm_call_budget,
)
from google_work_agent.application.orchestration.contracts import (
    RunBudgetV1,
    build_default_run_budget,
    consume_llm_provider_calls,
)
from google_work_agent.application.orchestration.prompt_input_guarded_provider import (
    PromptInputGuardedProvider,
)
from google_work_agent.application.orchestration.provider_dispatch_budget import (
    provider_dispatch_execution_scope,
)
from google_work_agent.ports.llm import (
    ActualRuntime,
    OutputSchemaDefinition,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
)


class _BudgetState(TypedDict):
    retry_budget: RunBudgetV1


class _NoopValidator:
    def validate(self, *, prompt_id: str, prompt_input: Mapping[str, object]) -> None:
        del prompt_id, prompt_input


class _Provider:
    provider_name = "checkpoint-test"
    runtime = ActualRuntime.API_LLM

    def __init__(self, *, timeout: bool = False) -> None:
        self.timeout = timeout
        self.dispatches = 0

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        runtime_policy: RuntimePolicy,
        api_key: str | None,
    ) -> ProviderResponsePayload:
        del prompt_ref, prompt_input, output_schema, runtime_policy, api_key
        self.dispatches += 1
        if self.timeout:
            raise TimeoutError("primary timeout after transport dispatch")
        return ProviderResponsePayload(
            content={"ok": True},
            model="checkpoint-model",
            provider_request_id="checkpoint-request",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
        )


def _prompt_ref() -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id="checkpoint.test",
        prompt_version="1",
        content_hash="0" * 64,
        agent_role="test",
        subgraph_name="test",
        node_name="dispatch",
        node_state="INITIAL",
        purpose="test",
        input_schema_version="1",
        output_schema_version="1",
    )


def _invoke(guarded: PromptInputGuardedProvider) -> None:
    guarded.invoke_structured(
        prompt_ref=_prompt_ref(),
        prompt_input={},
        output_schema=OutputSchemaDefinition(
            schema_version="1",
            json_schema={"type": "object"},
        ),
        runtime_policy=RuntimePolicy(),
        api_key=None,
    )


def _compile_graph(
    *,
    checkpointer: SqliteSaver,
    primary: PromptInputGuardedProvider,
    fallback: PromptInputGuardedProvider,
):
    def dispatch_node(state: _BudgetState) -> _BudgetState:
        ensure_llm_call_budget(state, provider_calls_requested=2)
        try:
            _invoke(primary)
        except TimeoutError:
            _invoke(fallback)
        return {
            "retry_budget": consume_llm_call_budget(state),
        }

    graph = StateGraph(_BudgetState)
    graph.add_node("dispatch", dispatch_node)
    graph.add_edge(START, "dispatch")
    graph.add_edge("dispatch", END)
    return graph.compile(checkpointer=checkpointer)


def test_handled_primary_timeout_fallback_budget_survives_sqlite_checkpoint_reopen(
    tmp_path: Path,
) -> None:
    checkpoint_path = tmp_path / "provider-budget-checkpoint.db"
    primary_provider = _Provider(timeout=True)
    fallback_provider = _Provider()
    primary = PromptInputGuardedProvider(primary_provider, _NoopValidator())
    fallback = PromptInputGuardedProvider(fallback_provider, _NoopValidator())

    initial_budget = consume_llm_provider_calls(
        build_default_run_budget(),
        provider_calls_consumed=3,
    )
    config = {"configurable": {"thread_id": "provider-budget-thread"}}

    connection = sqlite3.connect(checkpoint_path, check_same_thread=False)
    try:
        compiled = _compile_graph(
            checkpointer=SqliteSaver(connection),
            primary=primary,
            fallback=fallback,
        )
        with provider_dispatch_execution_scope():
            result = compiled.invoke({"retry_budget": initial_budget}, config=config)
        assert result["retry_budget"]["llm_calls_used"] == 5
    finally:
        connection.close()

    assert primary_provider.dispatches == 1
    assert fallback_provider.dispatches == 1

    reopened = sqlite3.connect(checkpoint_path, check_same_thread=False)
    try:
        restored = _compile_graph(
            checkpointer=SqliteSaver(reopened),
            primary=primary,
            fallback=fallback,
        ).get_state(config)
        restored_budget = restored.values["retry_budget"]
        assert restored_budget["llm_calls_used"] == 5
    finally:
        reopened.close()
