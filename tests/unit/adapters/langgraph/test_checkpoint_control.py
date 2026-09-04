from __future__ import annotations

import sqlite3
from typing import cast

from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite import SqliteSaver

from google_work_agent.adapters.langgraph.checkpoint_control import (
    LangGraphCheckpointControlAdapter,
)
from google_work_agent.ports.system.checkpoint_port import CheckpointPort
from google_work_agent.ports.system.contracts.checkpoint import GraphCheckpointEnvelopeV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    ConfirmationResumeControlV1,
)


class _CheckpointPort:
    def __init__(self, checkpoint: GraphCheckpointEnvelopeV1) -> None:
        self.checkpoint = checkpoint
        self.flush_count = 0

    def load_same_run_checkpoint(
        self, run_id: str, langgraph_thread_id: str
    ) -> GraphCheckpointEnvelopeV1 | None:
        if (
            run_id == self.checkpoint.run_id
            and langgraph_thread_id == self.checkpoint.langgraph_thread_id
        ):
            return self.checkpoint
        return None

    def flush(self) -> None:
        self.flush_count += 1


def _control(answer: str) -> ConfirmationResumeControlV1:
    return ConfirmationResumeControlV1(
        kind="CONFIRMATION_RESPONSE",
        confirmation_response={
            "schema_version": 1,
            "response_kind": "FREE_TEXT",
            "selected_option": None,
            "free_text": answer,
        },
        policy_confirmation_receipt=None,
    )


def test_consecutive_confirmation_responses__after_consumed_resume__replace_write_control() -> None:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    saver = SqliteSaver(connection)
    stored = saver.put(
        {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}},
        empty_checkpoint(),
        {},
        {},
    )
    checkpoint_id = cast(str, stored["configurable"]["checkpoint_id"])
    checkpoint = GraphCheckpointEnvelopeV1(
        schema_version=1,
        checkpoint_id=checkpoint_id,
        checkpoint_generation=1,
        run_id="run-1",
        langgraph_thread_id="thread-1",
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="resume-contract-v1",
        owner_scope="REQUEST_UNDERSTANDING",
        registered_resume_target=None,
        applied_handoff_id="handoff-1",
        execution_admission_id="admission-2",
        active_handoff_id="handoff-2",
        active_handoff_run_sequence=2,
        retrieval_cache_requirements=(),
        created_at_ms=1,
        checkpoint_blob=b"checkpoint",
    )
    port = _CheckpointPort(checkpoint)
    adapter = LangGraphCheckpointControlAdapter(
        checkpoint_port=cast(CheckpointPort, port),
        native_saver=saver,
    )

    first = _control("first answer")
    second = _control("second answer")
    adapter.materialize_control(checkpoint, first)
    adapter.materialize_control(checkpoint, second)

    assert adapter.contains_control(checkpoint, second)
    assert not adapter.contains_control(checkpoint, first)
    assert port.flush_count == 2
