"""LangGraph-native one-shot control materialization.

This is workflow adapter behavior, not part of the Core-facing CheckpointPort.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph._internal._constants import NULL_TASK_ID
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.pregel._io import map_command
from langgraph.types import Command

from google_work_agent.ports.system.checkpoint_port import CheckpointPort
from google_work_agent.ports.system.contracts.checkpoint import GraphCheckpointEnvelopeV1
from google_work_agent.ports.system.contracts.workflow_handoff import WorkflowControlEnvelopeV1


class LangGraphCheckpointControlAdapter:
    """Write native pending commands against the exact latest checkpoint."""

    def __init__(
        self,
        *,
        checkpoint_port: CheckpointPort,
        native_saver: BaseCheckpointSaver[str],
    ) -> None:
        self._checkpoint_port = checkpoint_port
        self._native_saver = native_saver

    def materialize_control(
        self,
        checkpoint: GraphCheckpointEnvelopeV1,
        control: WorkflowControlEnvelopeV1,
        *,
        goto_node: str | None = None,
    ) -> None:
        if control.kind != "CONFIRMATION_RESPONSE" and not goto_node:
            raise ValueError(f"{control.kind} requires a concrete runnable node")
        self._assert_exact_checkpoint(checkpoint)
        writes = _command_writes(native_resume_command(control, goto_node=goto_node))
        self._store_idempotent(checkpoint, writes)
        if not self.contains_control(checkpoint, control, goto_node=goto_node):
            raise ValueError("workflow control was not durably materialized")

    def contains_control(
        self,
        checkpoint: GraphCheckpointEnvelopeV1,
        control: WorkflowControlEnvelopeV1,
        *,
        goto_node: str | None = None,
    ) -> bool:
        self._assert_exact_checkpoint(checkpoint)
        pending = self._pending_null_writes(checkpoint)
        return all(
            pending.get(channel) == value
            for channel, value in _command_writes(
                native_resume_command(control, goto_node=goto_node)
            )
        )

    def materialize_resume_target(
        self, checkpoint: GraphCheckpointEnvelopeV1, *, goto_node: str
    ) -> None:
        if not goto_node:
            raise ValueError("resume target node is required")
        self._assert_exact_checkpoint(checkpoint)
        writes = _command_writes(native_resume_command(None, goto_node=goto_node))
        self._store_idempotent(checkpoint, writes)

    def _store_idempotent(
        self,
        checkpoint: GraphCheckpointEnvelopeV1,
        writes: list[tuple[str, object]],
    ) -> None:
        existing = self._pending_null_writes(checkpoint)
        for channel, value in writes:
            previous = existing.get(channel)
            if previous is not None and previous != value:
                raise ValueError(
                    f"checkpoint already contains a different pending write: {channel}"
                )
        self._native_saver.put_writes(self._config(checkpoint), writes, NULL_TASK_ID)
        self._checkpoint_port.flush()

    def _assert_exact_checkpoint(self, checkpoint: GraphCheckpointEnvelopeV1) -> None:
        current = self._checkpoint_port.load_same_run_checkpoint(
            checkpoint.run_id, checkpoint.langgraph_thread_id
        )
        if (
            current is None
            or current.checkpoint_id != checkpoint.checkpoint_id
            or current.checkpoint_generation != checkpoint.checkpoint_generation
            or current.checkpoint_blob != checkpoint.checkpoint_blob
        ):
            raise ValueError("workflow control requires the exact latest checkpoint")

    def _pending_null_writes(self, checkpoint: GraphCheckpointEnvelopeV1) -> dict[str, object]:
        item = self._native_saver.get_tuple(self._config(checkpoint))
        if item is None:
            raise ValueError("native checkpoint is missing")
        return {
            str(channel): value
            for task_id, channel, value in item.pending_writes or ()
            if task_id == NULL_TASK_ID
        }

    @staticmethod
    def _config(checkpoint: GraphCheckpointEnvelopeV1) -> RunnableConfig:
        return {
            "configurable": {
                "thread_id": checkpoint.langgraph_thread_id,
                "checkpoint_ns": "",
                "checkpoint_id": checkpoint.checkpoint_id,
            }
        }


def native_resume_command(
    control: WorkflowControlEnvelopeV1 | None,
    *,
    goto_node: str | None,
) -> Command[str]:
    """Build the single native command used by materialization and live resume."""
    if control is None:
        if not goto_node:
            raise ValueError("resume target node is required")
        return cast(Command[str], Command(goto=goto_node))
    if control.kind == "CONFIRMATION_RESPONSE":
        return cast(
            Command[str],
            Command(
                resume={
                    "confirmation_response": dict(control.confirmation_response),
                    "policy_confirmation_receipt": (
                        None
                        if control.policy_confirmation_receipt is None
                        else dict(control.policy_confirmation_receipt)
                    ),
                }
            ),
        )
    else:
        raw_control = cast(dict[str, object], asdict(control))
        update: dict[str, object] = {"__workflow_control__": raw_control}
        if control.kind == "CONTEXT_ADJUSTMENT":
            adjustment = cast(Mapping[str, object], control.adjustment)
            adjustment_kind = adjustment.get("kind")
            if adjustment_kind == "EXCLUDE_EVIDENCE":
                segment_ids = adjustment.get(
                    "excluded_segment_ids", adjustment.get("segment_ids", [])
                )
                if not isinstance(segment_ids, list) or not all(
                    isinstance(item, str) and item for item in segment_ids
                ):
                    raise ValueError("EXCLUDE_EVIDENCE requires stable segment ids")
                update["exclusion_obligation_segment_ids"] = list(segment_ids)
            elif adjustment_kind == "RETRIEVE_MORE":
                retrieval_need = adjustment.get("retrieval_need")
                if retrieval_need is None:
                    requested_information = adjustment.get("requested_information")
                    if not isinstance(requested_information, str) or not requested_information:
                        raise ValueError("RETRIEVE_MORE requires a bounded retrieval need")
                    retrieval_need = {
                        "schema_version": 1,
                        "required_information": requested_information,
                        "reason_codes": ["USER_CONTEXT_ADJUSTMENT"],
                    }
                if not isinstance(retrieval_need, dict):
                    raise ValueError("RETRIEVE_MORE retrieval_need must be an object")
                update["pending_user_retrieval_need"] = dict(retrieval_need)
            else:
                raise ValueError("unknown context adjustment kind")
        return cast(
            Command[str],
            Command(goto=goto_node, update=update) if goto_node else Command(update=update),
        )


def _command_writes(command: Command[str]) -> list[tuple[str, object]]:
    writes = list(map_command(command))
    if any(task_id != NULL_TASK_ID for task_id, _, _ in writes):
        raise AssertionError("workflow control writes must be checkpoint-level writes")
    return [(str(channel), value) for _, channel, value in writes]


__all__ = ["LangGraphCheckpointControlAdapter", "native_resume_command"]
