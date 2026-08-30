from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from google_work_agent.adapters.langgraph.confirmation_llm_runtime import (
    ConfirmationAwareLLMRuntime,
)
from google_work_agent.ports.llm import PromptReference
from google_work_agent.ports.system.contracts.observability import ObservabilityContext


@dataclass
class _Delegate:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def invoke_structured(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return "structured"

    def invoke_tool_call(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return "tool-call"


def _prompt(prompt_id: str) -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id=prompt_id,
        prompt_version="v1",
        content_hash="hash",
        agent_role="test",
        subgraph_name="test",
        node_name="test",
        node_state="INITIAL",
        purpose="test",
        input_schema_version="v1",
        output_schema_version="v1",
    )


def _response() -> dict[str, object]:
    return {
        "schema_version": 1,
        "response_kind": "FREE_TEXT",
        "selected_option": None,
        "free_text": "use the existing task",
    }


def _call(runtime: ConfirmationAwareLLMRuntime, prompt_id: str, *, run_id: str = "run-1") -> None:
    runtime.invoke_structured(
        prompt_ref=_prompt(prompt_id),
        prompt_input={"request_intent": {"schema_version": 2}},
        output_schema=object(),
        trace_context=ObservabilityContext(run_id=run_id),
    )


def test_confirmation_is_injected_only_into_originating_prompt_slot() -> None:
    delegate = _Delegate()
    runtime = ConfirmationAwareLLMRuntime(delegate)
    runtime.register(
        run_id="run-1",
        origin_target="retrieval.assess_sufficiency",
        response=_response(),  # type: ignore[arg-type]
    )

    _call(runtime, "retrieval.select_evidence")
    _call(runtime, "retrieval.assess_sufficiency")

    first = delegate.calls[0]["prompt_input"]
    second = delegate.calls[1]["prompt_input"]
    assert isinstance(first, Mapping)
    assert isinstance(second, Mapping)
    assert "confirmation_response" not in first
    assert second["confirmation_response"] == _response()


def test_confirmation_is_scoped_by_run_id() -> None:
    delegate = _Delegate()
    runtime = ConfirmationAwareLLMRuntime(delegate)
    runtime.register(
        run_id="run-1",
        origin_target="analysis.assess_information_gaps",
        response=_response(),  # type: ignore[arg-type]
    )

    _call(runtime, "work_analysis.assess_information_gaps", run_id="run-2")

    assert "confirmation_response" not in delegate.calls[0]["prompt_input"]


def test_clear_expires_pending_confirmation() -> None:
    delegate = _Delegate()
    runtime = ConfirmationAwareLLMRuntime(delegate)
    runtime.register(
        run_id="run-1",
        origin_target="review.aggregate_findings",
        response=_response(),  # type: ignore[arg-type]
    )
    runtime.clear(run_id="run-1")

    _call(runtime, "review.recheck_affected_dimensions")

    assert "confirmation_response" not in delegate.calls[0]["prompt_input"]


def test_tool_call_path_uses_the_same_bounded_projection() -> None:
    delegate = _Delegate()
    runtime = ConfirmationAwareLLMRuntime(delegate)
    runtime.register(
        run_id="run-1",
        origin_target="planning.compose_arguments_per_output_route",
        response=_response(),  # type: ignore[arg-type]
    )

    result = runtime.invoke_tool_call(
        prompt_ref=_prompt("planning.compose_arguments_per_output_route"),
        prompt_input={"output_route": {"route_id": "route-1"}},
        tools=[],
        mapper=lambda value: value,
        output_schema=object(),
        trace_context=ObservabilityContext(run_id="run-1"),
    )

    assert result == "tool-call"
    assert delegate.calls[0]["prompt_input"]["confirmation_response"] == _response()
