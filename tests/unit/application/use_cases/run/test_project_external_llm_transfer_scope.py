from dataclasses import dataclass, field

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


def test_project_external_llm_transfer_scope_publishes_bounded_metadata_and_replays() -> None:
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
    assert first.source_kinds == ("GMAIL", "TASKS")
    assert first.data_classes == ("RESOURCE_METADATA", "USER_REQUEST")
    assert replay == first
    assert checkpoint.calls == ["store", "flush"]


def test_project_external_llm_transfer_scope_changes_hash_and_revision() -> None:
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


def test_scope_checkpoint_is_not_published_before_sse_append_succeeds() -> None:
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

    assert checkpoint.calls == ["event"]
    assert checkpoint.scope is None


def test_scope_checkpoint_is_flushed_only_after_sse_append() -> None:
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

    assert checkpoint.calls == ["event", "store", "flush"]
