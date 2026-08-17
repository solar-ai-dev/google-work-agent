"""LLM runtime decorator for bounded same-owner confirmation re-entry.

The parent graph may have to restart an already-completed nested subgraph after
LangGraph resumes from the outer interrupt.  This decorator keeps that restart
semantically equivalent to a same-owner checkpoint resume: the validated user
answer is injected only into the Prompt slot that originally requested the
confirmation, never into unrelated nodes and never with interrupt metadata.
"""

from __future__ import annotations

from collections.abc import Mapping
from threading import Lock
from typing import Any

from google_work_agent.application.workflows.contracts import ConfirmationResponseV1


_ORIGIN_PROMPT_IDS: dict[str, frozenset[str]] = {
    "request_understanding.classify": frozenset({"request_understanding.classify"}),
    "tool_route.finalize": frozenset({"tool_route.determine_io_resources"}),
    "context.assess_sufficiency": frozenset({"retrieval.assess_sufficiency"}),
    "analysis.analyze": frozenset({"work_analysis.analyze"}),
    "planning.answer_only": frozenset({"planning.compose_answer"}),
    "planning.draft_plan": frozenset({"planning.compose_arguments"}),
    "review.inspect": frozenset({"review.inspect"}),
}


class ConfirmationAwareLLMRuntime:
    """Delegate StructuredLLMRuntime while adding one bounded owner response."""

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self._lock = Lock()
        self._pending: dict[str, tuple[str, ConfirmationResponseV1]] = {}

    def register(
        self,
        *,
        run_id: str,
        origin_target: str,
        response: ConfirmationResponseV1,
    ) -> None:
        if origin_target not in _ORIGIN_PROMPT_IDS:
            raise ValueError(f"unsupported confirmation origin target: {origin_target}")
        with self._lock:
            self._pending[run_id] = (origin_target, response)

    def clear(self, *, run_id: str) -> None:
        with self._lock:
            self._pending.pop(run_id, None)

    def invoke_structured(self, **kwargs: Any) -> Any:
        prompt_ref = kwargs.get("prompt_ref")
        prompt_input = kwargs.get("prompt_input")
        trace_context = kwargs.get("trace_context")
        run_id = getattr(trace_context, "run_id", None)
        prompt_id = getattr(prompt_ref, "prompt_id", None)

        if isinstance(run_id, str) and isinstance(prompt_id, str) and isinstance(
            prompt_input, Mapping
        ):
            with self._lock:
                pending = self._pending.get(run_id)
            if pending is not None:
                origin_target, response = pending
                if prompt_id in _ORIGIN_PROMPT_IDS[origin_target]:
                    kwargs = {
                        **kwargs,
                        "prompt_input": {
                            **dict(prompt_input),
                            "confirmation_response": dict(response),
                        },
                    }
        return self._delegate.invoke_structured(**kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)


__all__ = ["ConfirmationAwareLLMRuntime"]
