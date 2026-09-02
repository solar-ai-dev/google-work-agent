from dataclasses import dataclass, field
from typing import Literal, get_args, get_origin, get_type_hints

import pytest

from google_work_agent.application.use_cases.run.project_external_llm_transfer_scope import (
    ProjectExternalLlmTransferScopeHandler,
    ProjectExternalLlmTransferScopeQueryV1,
)
from google_work_agent.ports.system.contracts.external_llm_transfer_scope import (
    ExternalLlmTransferScopeV1,
)


@dataclass
class _Checkpoint:
    scope: ExternalLlmTransferScopeV1 | None = None
    calls: list[str] = field(default_factory=list)

    def load_external_llm_scope(self, run_id: str) -> ExternalLlmTransferScopeV1 | None:
        assert run_id == "run-1"
        return self.scope

    def store_external_llm_scope(self, scope: ExternalLlmTransferScopeV1) -> None:
        self.calls.append("store")
        self.scope = scope

    def flush(self) -> None:
        self.calls.append("flush")


@dataclass
class _Events:
    calls: list[str]
    fail: bool = False

    def __call__(self, command: object) -> None:
        del command
        self.calls.append("event")
        if self.fail:
            raise RuntimeError("SSE_UNAVAILABLE")


def test_external_llm_transfer__scope_uses_exact__canonical_list_contract() -> None:
    annotations = get_type_hints(ExternalLlmTransferScopeV1)

    assert annotations["source_kinds"] == list[str]
    assert get_origin(annotations["data_classes"]) is list
    data_class = get_args(annotations["data_classes"])[0]
    assert get_origin(data_class) is Literal
    assert set(get_args(data_class)) == {
        "USER_REQUEST",
        "RESOURCE_METADATA",
        "EVIDENCE_EXCERPT",
        "PLAN_CONTEXT",
    }

    with pytest.raises(TypeError, match="collections must be lists"):
        ExternalLlmTransferScopeV1(
            1,
            "run-1",
            1,
            "scope-hash",
            ("USER_REQUEST",),  # type: ignore[arg-type]
            ("USER_REQUEST",),  # type: ignore[arg-type]
        )


def test_project_external_llm__transfer_scope_publishes__bounded_metadata_and_replays() -> None:
    checkpoint = _Checkpoint()
    handler = ProjectExternalLlmTransferScopeHandler(checkpoint)  # type: ignore[arg-type]
    query = ProjectExternalLlmTransferScopeQueryV1(
        1,
        "run-1",
        ("TASKS", "GMAIL", "TASKS"),
        ("RESOURCE_METADATA", "USER_REQUEST"),
    )

    first = handler(query)
    replay = handler(query)

    assert first is not None
    assert first.scope_revision == 1
    assert first.source_kinds == ["GMAIL", "TASKS"]
    assert first.data_classes == ["RESOURCE_METADATA", "USER_REQUEST"]
    assert replay == first
    assert checkpoint.calls == ["store", "flush"]


def test_project_external_llm__transfer_scope_changes__hash_and_revision() -> None:
    checkpoint = _Checkpoint()
    handler = ProjectExternalLlmTransferScopeHandler(checkpoint)  # type: ignore[arg-type]
    first = handler(
        ProjectExternalLlmTransferScopeQueryV1(1, "run-1", ("GMAIL",), ("USER_REQUEST",))
    )
    second = handler(
        ProjectExternalLlmTransferScopeQueryV1(
            1, "run-1", ("GMAIL",), ("USER_REQUEST", "EVIDENCE_EXCERPT")
        )
    )

    assert first is not None and second is not None
    assert second.scope_revision == 2
    assert second.scope_hash != first.scope_hash


def test_scope_checkpoint__remains_durable_when__sse_append_fails() -> None:
    checkpoint = _Checkpoint()
    handler = ProjectExternalLlmTransferScopeHandler(
        checkpoint,  # type: ignore[arg-type]
        _Events(checkpoint.calls, fail=True),  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="SSE_UNAVAILABLE"):
        handler(
            ProjectExternalLlmTransferScopeQueryV1(
                1,
                "run-1",
                ("USER_REQUEST",),
                ("USER_REQUEST",),
                occurred_at_ms=1,
            )
        )

    assert checkpoint.calls == ["store", "flush", "event"]
    assert checkpoint.scope is not None


def test_scope_checkpoint__is_flushed__before_sse_append() -> None:
    checkpoint = _Checkpoint()
    handler = ProjectExternalLlmTransferScopeHandler(
        checkpoint,  # type: ignore[arg-type]
        _Events(checkpoint.calls),  # type: ignore[arg-type]
    )

    handler(
        ProjectExternalLlmTransferScopeQueryV1(
            1,
            "run-1",
            ("USER_REQUEST",),
            ("USER_REQUEST",),
            occurred_at_ms=1,
        )
    )

    assert checkpoint.calls == ["store", "flush", "event"]


def test_scope_event_is__retried_after_checkpoint_first__crash_without_rewriting_scope() -> None:
    checkpoint = _Checkpoint()
    failing_handler = ProjectExternalLlmTransferScopeHandler(
        checkpoint,  # type: ignore[arg-type]
        _Events(checkpoint.calls, fail=True),  # type: ignore[arg-type]
    )
    query = ProjectExternalLlmTransferScopeQueryV1(
        1,
        "run-1",
        ("USER_REQUEST",),
        ("USER_REQUEST",),
        occurred_at_ms=1,
    )

    with pytest.raises(RuntimeError, match="SSE_UNAVAILABLE"):
        failing_handler(query)

    recovered_handler = ProjectExternalLlmTransferScopeHandler(
        checkpoint,  # type: ignore[arg-type]
        _Events(checkpoint.calls),  # type: ignore[arg-type]
    )
    recovered = recovered_handler(query)

    assert recovered == checkpoint.scope
    assert checkpoint.calls == ["store", "flush", "event", "event"]
