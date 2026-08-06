"""Workflow runtime port definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

type JsonValue = Any


@dataclass(frozen=True, slots=True)
class WorkflowInvocationResult:
    """Minimal result returned from the workflow runtime."""

    run_id: str
    workflow_key: str
    payload: dict[str, JsonValue]


class WorkflowRuntime(Protocol):
    """Minimal workflow runtime surface for the product core."""

    def start(
        self,
        *,
        run_id: str,
        workflow_key: str,
        payload: dict[str, JsonValue],
    ) -> WorkflowInvocationResult:
        """Start a workflow run."""

    def resume(
        self,
        *,
        run_id: str,
        workflow_key: str,
        payload: dict[str, JsonValue],
    ) -> WorkflowInvocationResult:
        """Resume a workflow run."""

    def request_cancel(
        self,
        *,
        run_id: str,
        workflow_key: str,
        payload: dict[str, JsonValue],
    ) -> WorkflowInvocationResult:
        """Request cancellation for a workflow run."""

    def recover_open_run(
        self,
        *,
        run_id: str,
        workflow_key: str,
        payload: dict[str, JsonValue],
    ) -> WorkflowInvocationResult:
        """Recover an open workflow run."""
