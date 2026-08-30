"""LLM runtime decorator for bounded same-owner confirmation re-entry.

The parent graph may have to restart an already-completed nested subgraph after
LangGraph resumes from the outer interrupt. This decorator keeps that restart
semantically equivalent to a same-owner checkpoint resume: the validated user
answer is injected only into the Prompt slot that originally requested the
confirmation, never into unrelated nodes and never with interrupt metadata.
"""

from __future__ import annotations

from collections.abc import Mapping
from threading import Lock
from typing import Any

from google_work_agent.application.orchestration.contracts import ConfirmationResponseProjectionV1

_ORIGIN_PROMPT_IDS: dict[str, frozenset[str]] = {
    "request.detect_ambiguity": frozenset(
        {
            "request_understanding.identify_goal",
            "request_understanding.detect_ambiguity",
        }
    ),
    "tool_route.finalize": frozenset({"tool_routing.determine_io_resources"}),
    "acquisition.plan_sources": frozenset(
        {
            "retrieval.plan_query",
            "profile.single.request_source.initial",
            "profile.three.stage1.initial",
        }
    ),
    "retrieval.assess_sufficiency": frozenset({"retrieval.assess_sufficiency"}),
    "analysis.assess_information_gaps": frozenset({"work_analysis.assess_information_gaps"}),
    "analysis.assess_operational_risks": frozenset({"work_analysis.assess_operational_risks"}),
    "planning.outline_answer": frozenset({"planning.outline_answer", "planning.compose_answer"}),
    "planning.compose_arguments_per_output_route": frozenset(
        {"planning.compose_arguments_per_output_route"}
    ),
    "review.inspect": frozenset({"review.inspect"}),
}


class ConfirmationAwareLLMRuntime:
    """Delegate StructuredLLMRuntime while adding one bounded owner response."""

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self._lock = Lock()
        self._pending: dict[str, tuple[str, ConfirmationResponseProjectionV1]] = {}

    def register(
        self,
        *,
        run_id: str,
        origin_target: str,
        response: ConfirmationResponseProjectionV1,
    ) -> None:
        if origin_target not in _ORIGIN_PROMPT_IDS:
            raise ValueError(f"unsupported confirmation origin target: {origin_target}")
        with self._lock:
            self._pending[run_id] = (origin_target, response)

    def clear(self, *, run_id: str) -> None:
        with self._lock:
            self._pending.pop(run_id, None)

    def invoke_structured(self, **kwargs: Any) -> Any:
        return self._delegate.invoke_structured(**self._with_confirmation(kwargs))

    def invoke_tool_call(self, **kwargs: Any) -> Any:
        return self._delegate.invoke_tool_call(**self._with_confirmation(kwargs))

    def _with_confirmation(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        prompt_ref = kwargs.get("prompt_ref")
        prompt_input = kwargs.get("prompt_input")
        trace_context = kwargs.get("trace_context")
        run_id = getattr(trace_context, "run_id", None)
        prompt_id = getattr(prompt_ref, "prompt_id", None)

        if not (
            isinstance(run_id, str)
            and isinstance(prompt_id, str)
            and isinstance(prompt_input, Mapping)
        ):
            return kwargs
        with self._lock:
            pending = self._pending.get(run_id)
        if pending is None:
            return kwargs
        origin_target, response = pending
        if prompt_id not in _ORIGIN_PROMPT_IDS[origin_target]:
            return kwargs
        return {
            **kwargs,
            "prompt_input": {
                **dict(prompt_input),
                "confirmation_response": dict(response),
            },
        }

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)


__all__ = ["ConfirmationAwareLLMRuntime"]
