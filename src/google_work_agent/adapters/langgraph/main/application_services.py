"""Typed composition boundary for Application services consumed by LangGraph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class WorkflowApplicationServices:
    start_analysis: Any
    get_run_snapshot: Any
    build_terminal_message: Any
    emit_terminal_trace: Any
    project_terminal_event: Any | None
    begin_retrieval: Any
    begin_planning: Any
    request_confirmation: Any
    domain_validation: Any
    complete_answer_only: Any
    complete_read_only_run: Any
    complete_write_run: Any
    block_run: Any
    publish_read_plan: Any
    claim_read: Any
    complete_read: Any
    finalize_read: Any
    fail_read: Any
    publish_write_plan: Any
    build_claim_context: Any
    begin_execution_attempt: Any
    abort_claimed_execution: Any
    classify_dispatch_result: Any
    expire_approval: Any
    refresh_expired_action: Any
    claim_execution: Any
    store_write_success: Any
    mark_write_failed: Any
    mark_write_unknown: Any
    verify_effect: Any
    store_verification: Any
    require_recovery: Any
    resolve_recovery: Any
    require_write_reauth: Any
    lookup_unknown_result: Any
    recover_existing_result: Any
    resolve_as_failed: Any
    begin_write_verification: Any
    resolve_resource_ref: Any
    cancel_pending_action: Any
    finalize_cancel: Any
    continue_cancel_resolution: Any
    record_review_result: Any
    validate_action_arguments: Any


class WorkflowRuntimeHooks:
    """Late-bound structural callbacks used while composition precedes runtime creation."""

    def __init__(self) -> None:
        self._runtime: Any | None = None

    def bind(self, runtime: Any) -> None:
        if self._runtime is not None:
            raise RuntimeError("workflow runtime hooks are already bound")
        self._runtime = runtime

    def call(self, name: str, *args: object, **kwargs: object) -> Any:
        if self._runtime is None:
            raise RuntimeError("workflow runtime hooks are not bound")
        callback = getattr(self._runtime, name)
        return callback(*args, **kwargs)


__all__ = ["WorkflowApplicationServices", "WorkflowRuntimeHooks"]
