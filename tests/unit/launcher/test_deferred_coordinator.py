"""Unit tests for _DeferredCoordinator command forwarding.

Regression coverage for the bug where POST /api/v1/runs returned
503 SERVICE_BUSY with detail_code=AttributeError: `local_run_coordinator`
is set once as a real instance attribute on `_DeferredApiContainer`, so it
never falls through to `__getattr__`'s post-init delegation. Before this
fix, `_DeferredCoordinator` only forwarded start()/stop(); every call to
enqueue_start/enqueue_resume/request_cancel hit the placeholder itself
(which had no such methods) forever, even after core initialization
completed and the real coordinator was bound.
"""

from __future__ import annotations

import pytest

from google_work_agent.launcher.dev import _DeferredCoordinator


class _RecordingCoordinator:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.start_calls: list[dict[str, object]] = []
        self.resume_calls: list[dict[str, object]] = []
        self.cancel_calls: list[dict[str, object]] = []

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def enqueue_start(self, *, run_id: str, request_id: str, command_id: str) -> None:
        self.start_calls.append(
            {"run_id": run_id, "request_id": request_id, "command_id": command_id}
        )

    def enqueue_resume(
        self,
        *,
        run_id: str,
        request_id: str,
        command_id: str | None,
        resume_kind: str,
        resume_payload: dict[str, object],
    ) -> None:
        self.resume_calls.append(
            {
                "run_id": run_id,
                "request_id": request_id,
                "command_id": command_id,
                "resume_kind": resume_kind,
                "resume_payload": resume_payload,
            }
        )

    def request_cancel(self, *, run_id: str, request_id: str, reason_code: str) -> None:
        self.cancel_calls.append(
            {"run_id": run_id, "request_id": request_id, "reason_code": reason_code}
        )


def test_enqueue_start_raises_a_clear_error_before_the_delegate_is_bound() -> None:
    deferred = _DeferredCoordinator()

    with pytest.raises(RuntimeError, match="core initialization is incomplete"):
        deferred.enqueue_start(run_id="run-1", request_id="req-1", command_id="cmd-1")


def test_enqueue_resume_raises_a_clear_error_before_the_delegate_is_bound() -> None:
    deferred = _DeferredCoordinator()

    with pytest.raises(RuntimeError, match="core initialization is incomplete"):
        deferred.enqueue_resume(
            run_id="run-1",
            request_id="req-1",
            command_id="cmd-1",
            resume_kind="REAUTH_COMPLETED",
            resume_payload={},
        )


def test_request_cancel_raises_a_clear_error_before_the_delegate_is_bound() -> None:
    deferred = _DeferredCoordinator()

    with pytest.raises(RuntimeError, match="core initialization is incomplete"):
        deferred.request_cancel(run_id="run-1", request_id="req-1", reason_code="user_requested")


def test_enqueue_start_forwards_to_the_bound_delegate_after_core_initialization() -> None:
    deferred = _DeferredCoordinator()
    delegate = _RecordingCoordinator()
    deferred.bind(delegate)  # type: ignore[arg-type]

    deferred.enqueue_start(run_id="run-1", request_id="req-1", command_id="cmd-1")

    assert delegate.start_calls == [
        {"run_id": "run-1", "request_id": "req-1", "command_id": "cmd-1"}
    ]


def test_enqueue_resume_forwards_to_the_bound_delegate_after_core_initialization() -> None:
    deferred = _DeferredCoordinator()
    delegate = _RecordingCoordinator()
    deferred.bind(delegate)  # type: ignore[arg-type]

    deferred.enqueue_resume(
        run_id="run-1",
        request_id="req-1",
        command_id="cmd-1",
        resume_kind="REAUTH_COMPLETED",
        resume_payload={"a": 1},
    )

    assert delegate.resume_calls == [
        {
            "run_id": "run-1",
            "request_id": "req-1",
            "command_id": "cmd-1",
            "resume_kind": "REAUTH_COMPLETED",
            "resume_payload": {"a": 1},
        }
    ]


def test_request_cancel_forwards_to_the_bound_delegate_after_core_initialization() -> None:
    deferred = _DeferredCoordinator()
    delegate = _RecordingCoordinator()
    deferred.bind(delegate)  # type: ignore[arg-type]

    deferred.request_cancel(run_id="run-1", request_id="req-1", reason_code="user_requested")

    assert delegate.cancel_calls == [
        {"run_id": "run-1", "request_id": "req-1", "reason_code": "user_requested"}
    ]


def test_bind_after_start_still_starts_the_delegate() -> None:
    deferred = _DeferredCoordinator()
    deferred.start()
    delegate = _RecordingCoordinator()

    deferred.bind(delegate)  # type: ignore[arg-type]

    assert delegate.started is True
