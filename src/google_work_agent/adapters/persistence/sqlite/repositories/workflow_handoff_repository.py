"""SQLite realization of the durable workflow handoff outbox."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from json import dumps, loads
from typing import Any, Literal, cast

from google_work_agent.ports.system.contracts.workflow_binding import GraphProfileIdV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    AgentNodeResumeTargetV2,
    CompiledAgentSubgraphIdV1,
    ConfirmationResumeControlV1,
    ContextAdjustmentControlV1,
    MainControlResumeTargetV2,
    MainResumeStageIdV1,
    RequestedModeV1,
    RetrievalCacheRestartControlV1,
    RunExecutionRefV1,
    SemanticAgentOwnerIdV1,
    WorkflowControlEnvelopeV1,
    WorkflowExecutionAdmissionV1,
    WorkflowExecutionBindingV1,
    WorkflowExecutionReleaseReasonV1,
    WorkflowExecutionSettlementV1,
    WorkflowHandoffStageV1,
    WorkflowHandoffStatusV1,
    WorkflowHandoffV1,
    WorkflowSubmitReasonV1,
)


class WorkflowHandoffConflictError(RuntimeError):
    """A persisted handoff/version/admission fence did not match."""


class SqliteWorkflowHandoffRepository:
    def __init__(self, connection: sqlite3.Connection, *, now_ms: Callable[[], int]) -> None:
        self._connection = connection
        self._now_ms = now_ms

    def stage_pending(self, stage: WorkflowHandoffStageV1) -> WorkflowHandoffV1:
        replay = self.get_by_trigger_command_id(stage.trigger_command_id)
        if replay is not None:
            if _stage_identity(replay) != stage:
                raise WorkflowHandoffConflictError("trigger command already owns another handoff")
            return replay
        run_row = self._connection.execute(
            "SELECT langgraph_thread_id, requested_mode FROM runs WHERE id = ?;",
            (stage.execution.run_id,),
        ).fetchone()
        if run_row is None:
            raise LookupError(f"run not found: {stage.execution.run_id}")
        if (
            str(run_row["langgraph_thread_id"]) != stage.execution.langgraph_thread_id
            or str(run_row["requested_mode"]) != stage.execution.requested_mode
        ):
            raise WorkflowHandoffConflictError("handoff execution does not match persisted Run")
        sequence_row = self._connection.execute(
            """
            SELECT COALESCE(MAX(run_sequence), 0) + 1 AS next_sequence
            FROM workflow_handoffs WHERE run_id = ?;
            """,
            (stage.execution.run_id,),
        ).fetchone()
        run_sequence = int(sequence_row["next_sequence"])
        self._connection.execute(
            """
            INSERT INTO workflow_handoffs (
                handoff_id, trigger_command_id, run_id, langgraph_thread_id,
                graph_profile, graph_version, requested_mode, execution_kind,
                resume_target_json, checkpoint_id, checkpoint_generation, run_sequence,
                control_kind, control_payload_json, control_payload_hash, status,
                created_at_ms, version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, 0);
            """,
            (
                stage.handoff_id,
                stage.trigger_command_id,
                stage.execution.run_id,
                stage.execution.langgraph_thread_id,
                stage.execution.graph_profile,
                stage.execution.graph_version,
                stage.execution.requested_mode,
                stage.execution.execution_kind,
                _json_or_none(stage.execution.resume_target),
                stage.checkpoint_id,
                stage.checkpoint_generation,
                run_sequence,
                stage.control_kind,
                _json_or_none(stage.control),
                stage.control_payload_hash,
                self._now_ms(),
            ),
        )
        return self._required(stage.handoff_id)

    def get(self, handoff_id: str) -> WorkflowHandoffV1 | None:
        row = self._connection.execute(
            "SELECT * FROM workflow_handoffs WHERE handoff_id = ?;", (handoff_id,)
        ).fetchone()
        return None if row is None else _to_handoff(row)

    def get_by_trigger_command_id(self, trigger_command_id: str) -> WorkflowHandoffV1 | None:
        row = self._connection.execute(
            "SELECT * FROM workflow_handoffs WHERE trigger_command_id = ?;",
            (trigger_command_id,),
        ).fetchone()
        return None if row is None else _to_handoff(row)

    def get_dispatch_head(self, run_id: str) -> WorkflowHandoffV1 | None:
        row = self._connection.execute(
            """
            SELECT * FROM workflow_handoffs
            WHERE run_id = ? AND status IN ('PENDING', 'DISPATCHED', 'BLOCKED_BINDING')
            ORDER BY run_sequence ASC LIMIT 1;
            """,
            (run_id,),
        ).fetchone()
        return None if row is None else _to_handoff(row)

    def list_redriveable(self, limit: int) -> list[WorkflowHandoffV1]:
        _require_limit(limit)
        rows = self._connection.execute(
            """
            WITH ranked AS (
                SELECT
                    workflow_handoffs.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY run_id
                        ORDER BY
                            CASE
                                WHEN status = 'CONSUMED'
                                     AND applied_checkpoint_id IS NOT NULL THEN 0
                                WHEN status = 'BLOCKED_BINDING' THEN 1
                                ELSE 2
                            END,
                            CASE
                                WHEN status = 'CONSUMED'
                                     AND applied_checkpoint_id IS NOT NULL THEN -run_sequence
                                ELSE run_sequence
                            END ASC
                    ) AS run_rank
                FROM workflow_handoffs
                WHERE
                    (status = 'CONSUMED' AND applied_checkpoint_id IS NOT NULL)
                    OR status IN ('BLOCKED_BINDING', 'PENDING', 'DISPATCHED')
            )
            SELECT * FROM ranked
            WHERE run_rank = 1
            ORDER BY
                CASE
                    WHEN status = 'CONSUMED' AND applied_checkpoint_id IS NOT NULL THEN 0
                    WHEN status = 'BLOCKED_BINDING' THEN 1
                    ELSE 2
                END,
                created_at_ms ASC,
                handoff_id ASC
            LIMIT ?;
            """,
            (limit,),
        ).fetchall()
        return [_to_handoff(row) for row in rows]

    def list_blocked_binding(self, limit: int) -> list[WorkflowHandoffV1]:
        _require_limit(limit)
        rows = self._connection.execute(
            """
            SELECT * FROM workflow_handoffs WHERE status = 'BLOCKED_BINDING'
            ORDER BY created_at_ms ASC, handoff_id ASC LIMIT ?;
            """,
            (limit,),
        ).fetchall()
        return [_to_handoff(row) for row in rows]

    def claim_execution_admission(
        self,
        handoff_id: str,
        expected_version: int,
        admission: WorkflowExecutionAdmissionV1,
    ) -> WorkflowHandoffV1:
        current = self._required(handoff_id)
        if current.version != expected_version:
            raise WorkflowHandoffConflictError("handoff version changed")
        if (
            admission.handoff_id != current.handoff_id
            or admission.handoff_run_sequence != current.run_sequence
            or admission.effective_binding.run_id != current.execution.run_id
        ):
            raise WorkflowHandoffConflictError("admission identity does not match handoff")
        if current.execution_admission is not None:
            if current.execution_admission == admission:
                return current
            raise WorkflowHandoffConflictError("handoff already has another active admission")
        self._require_run_epoch(current.execution.run_id, admission.expected_run_version)
        if admission.submission_kind == "NORMAL_HANDOFF":
            head = self.get_dispatch_head(current.execution.run_id)
            if head is None or head.handoff_id != handoff_id or current.status != "PENDING":
                raise WorkflowHandoffConflictError(
                    "NORMAL_HANDOFF requires the PENDING dispatch head"
                )
            status = "DISPATCHED"
            dispatched_at_ms: int | None = self._now_ms()
        else:
            if current.status != "CONSUMED":
                raise WorkflowHandoffConflictError("recovery admission requires a CONSUMED handoff")
            status = "CONSUMED"
            dispatched_at_ms = None
        cursor = self._connection.execute(
            """
            UPDATE workflow_handoffs
            SET status = ?, execution_admission_json = ?,
                dispatched_at_ms = COALESCE(?, dispatched_at_ms),
                last_submit_reason = NULL, version = version + 1
            WHERE handoff_id = ? AND version = ? AND execution_admission_json IS NULL;
            """,
            (status, _canonical_json(admission), dispatched_at_ms, handoff_id, expected_version),
        )
        if cursor.rowcount != 1:
            raise WorkflowHandoffConflictError("execution admission claim lost its CAS")
        return self._required(handoff_id)

    def release_execution_admission(
        self,
        handoff_id: str,
        expected_version: int,
        admission_id: str,
        reason_code: WorkflowExecutionReleaseReasonV1,
    ) -> WorkflowHandoffV1:
        current = self._required_admission(handoff_id, expected_version, admission_id)
        admission = cast(WorkflowExecutionAdmissionV1, current.execution_admission)
        run_version = self._run_version(current.execution.run_id)
        stale = run_version != admission.expected_run_version
        if reason_code == "AUTHORITY_EPOCH_CHANGED" and not stale:
            raise WorkflowHandoffConflictError("Run authority epoch has not changed")
        if stale:
            return self._retire_stale(current)
        if reason_code == "AUTHORITY_EPOCH_CHANGED":
            raise WorkflowHandoffConflictError("invalid authority release")
        if reason_code == "BINDING_MISMATCH" and admission.submission_kind == "NORMAL_HANDOFF":
            # A NORMAL dispatch head whose binding no longer validates is not
            # redriveable as ordinary PENDING -- it must wait for canonical
            # RequireRecovery(CHECKPOINT_MISMATCH) reconciliation.
            status = "BLOCKED_BINDING"
        else:
            status = "PENDING" if admission.submission_kind == "NORMAL_HANDOFF" else "CONSUMED"
        self._connection.execute(
            """
            UPDATE workflow_handoffs
            SET status = ?, execution_admission_json = NULL,
                last_submit_reason = ?, version = version + 1
            WHERE handoff_id = ? AND version = ?;
            """,
            (status, reason_code, handoff_id, expected_version),
        )
        return self._required(handoff_id)

    def mark_consumed_and_clear_payload(
        self,
        handoff_id: str,
        expected_version: int,
        admission_id: str,
        applied_checkpoint_id: str,
        applied_checkpoint_generation: int,
    ) -> WorkflowExecutionSettlementV1:
        return self._settle(
            handoff_id,
            expected_version,
            admission_id,
            applied_checkpoint_id,
            applied_checkpoint_generation,
            require_recovery=False,
        )

    def complete_recovery_admission(
        self,
        handoff_id: str,
        expected_version: int,
        admission_id: str,
        admission_checkpoint_id: str,
        admission_checkpoint_generation: int,
    ) -> WorkflowExecutionSettlementV1:
        return self._settle(
            handoff_id,
            expected_version,
            admission_id,
            admission_checkpoint_id,
            admission_checkpoint_generation,
            require_recovery=True,
        )

    def mark_superseded(
        self, handoff_id: str, expected_version: int, reason_code: str
    ) -> WorkflowHandoffV1:
        del reason_code
        current = self._required(handoff_id)
        if current.version != expected_version or current.execution_admission is not None:
            raise WorkflowHandoffConflictError(
                "only an unadmitted current handoff can be superseded"
            )
        if current.status in {"CONSUMED", "SUPERSEDED"}:
            return current
        self._connection.execute(
            """
            UPDATE workflow_handoffs
            SET status = 'SUPERSEDED', control_payload_json = NULL,
                superseded_at_ms = ?, version = version + 1
            WHERE handoff_id = ? AND version = ?;
            """,
            (self._now_ms(), handoff_id, expected_version),
        )
        return self._required(handoff_id)

    def supersede_unconsumed_for_run(
        self, run_id: str, reason_code: str
    ) -> list[WorkflowHandoffV1]:
        del reason_code
        rows = self._connection.execute(
            """
            SELECT handoff_id FROM workflow_handoffs
            WHERE run_id = ? AND status IN ('PENDING', 'DISPATCHED', 'BLOCKED_BINDING')
              AND execution_admission_json IS NULL
            ORDER BY run_sequence ASC;
            """,
            (run_id,),
        ).fetchall()
        handoff_ids = [str(row["handoff_id"]) for row in rows]
        if handoff_ids:
            self._connection.execute(
                """
                UPDATE workflow_handoffs
                SET status = 'SUPERSEDED', control_payload_json = NULL,
                    superseded_at_ms = ?, version = version + 1
                WHERE run_id = ? AND status IN ('PENDING', 'DISPATCHED', 'BLOCKED_BINDING')
                  AND execution_admission_json IS NULL;
                """,
                (self._now_ms(), run_id),
            )
        return [self._required(handoff_id) for handoff_id in handoff_ids]

    def _settle(
        self,
        handoff_id: str,
        expected_version: int,
        admission_id: str,
        checkpoint_id: str,
        checkpoint_generation: int,
        *,
        require_recovery: bool,
    ) -> WorkflowExecutionSettlementV1:
        if not checkpoint_id or checkpoint_generation < 1:
            raise ValueError("settlement requires committed checkpoint evidence")
        current = self._required_admission(handoff_id, expected_version, admission_id)
        admission = cast(WorkflowExecutionAdmissionV1, current.execution_admission)
        is_recovery = admission.submission_kind == "CONSUMED_CONTINUATION_RECOVERY"
        if is_recovery != require_recovery:
            raise WorkflowHandoffConflictError("settlement method does not match admission kind")
        if self._run_version(current.execution.run_id) != admission.expected_run_version:
            retired = self._retire_stale(current)
            return WorkflowExecutionSettlementV1(1, "AUTHORITY_STALE_RETIRED", retired)
        self._connection.execute(
            """
            UPDATE workflow_handoffs
            SET status = 'CONSUMED', control_payload_json = NULL,
                execution_admission_json = NULL, applied_checkpoint_id = ?,
                applied_checkpoint_generation = ?, consumed_at_ms = COALESCE(consumed_at_ms, ?),
                version = version + 1
            WHERE handoff_id = ? AND version = ?;
            """,
            (checkpoint_id, checkpoint_generation, self._now_ms(), handoff_id, expected_version),
        )
        return WorkflowExecutionSettlementV1(1, "SETTLED", self._required(handoff_id))

    def _retire_stale(self, current: WorkflowHandoffV1) -> WorkflowHandoffV1:
        admission = cast(WorkflowExecutionAdmissionV1, current.execution_admission)
        if admission.submission_kind == "NORMAL_HANDOFF":
            self._connection.execute(
                """
                UPDATE workflow_handoffs
                SET status = 'SUPERSEDED', control_payload_json = NULL,
                    execution_admission_json = NULL, superseded_at_ms = ?,
                    version = version + 1
                WHERE handoff_id = ? AND version = ?;
                """,
                (self._now_ms(), current.handoff_id, current.version),
            )
        else:
            self._connection.execute(
                """
                UPDATE workflow_handoffs
                SET execution_admission_json = NULL, version = version + 1
                WHERE handoff_id = ? AND version = ?;
                """,
                (current.handoff_id, current.version),
            )
        return self._required(current.handoff_id)

    def _required(self, handoff_id: str) -> WorkflowHandoffV1:
        handoff = self.get(handoff_id)
        if handoff is None:
            raise LookupError(f"workflow handoff not found: {handoff_id}")
        return handoff

    def _required_admission(
        self, handoff_id: str, expected_version: int, admission_id: str
    ) -> WorkflowHandoffV1:
        handoff = self._required(handoff_id)
        if handoff.version != expected_version:
            raise WorkflowHandoffConflictError("handoff version changed")
        if (
            handoff.execution_admission is None
            or handoff.execution_admission.admission_id != admission_id
        ):
            raise WorkflowHandoffConflictError("execution admission does not match")
        return handoff

    def _run_version(self, run_id: str) -> int:
        row = self._connection.execute(
            "SELECT version FROM runs WHERE id = ?;", (run_id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"run not found: {run_id}")
        return int(row["version"])

    def _require_run_epoch(self, run_id: str, expected_version: int) -> None:
        if self._run_version(run_id) != expected_version:
            raise WorkflowHandoffConflictError("Run authority epoch changed")


def _canonical_json(value: object) -> str:
    serializable: object = (
        asdict(cast(Any, value)) if hasattr(value, "__dataclass_fields__") else value
    )
    return dumps(serializable, sort_keys=True, separators=(",", ":"))


def _json_or_none(value: object | None) -> str | None:
    return None if value is None else _canonical_json(value)


def deserialize_resume_target(
    value: object | None,
) -> AgentNodeResumeTargetV2 | MainControlResumeTargetV2 | None:
    if value is None:
        return None
    item = cast(dict[str, object], value)
    profile = cast(GraphProfileIdV1, str(item["graph_profile"]))
    if item["kind"] == "AGENT_NODE":
        return AgentNodeResumeTargetV2(
            kind="AGENT_NODE",
            semantic_owner_id=cast(SemanticAgentOwnerIdV1, str(item["semantic_owner_id"])),
            compiled_subgraph_id=cast(CompiledAgentSubgraphIdV1, str(item["compiled_subgraph_id"])),
            node_id=str(item["node_id"]),
            graph_profile=profile,
            graph_version=str(item["graph_version"]),
        )
    return MainControlResumeTargetV2(
        kind="MAIN_CONTROL",
        stage_id=cast(MainResumeStageIdV1, str(item["stage_id"])),
        graph_profile=profile,
        graph_version=str(item["graph_version"]),
    )


def _control(kind: str, value: object | None) -> WorkflowControlEnvelopeV1 | None:
    if value is None:
        return None
    item = cast(dict[str, object], value)
    if kind == "CONFIRMATION_RESPONSE":
        receipt = item.get("policy_confirmation_receipt")
        return ConfirmationResumeControlV1(
            kind="CONFIRMATION_RESPONSE",
            confirmation_response=cast(dict[str, object], item["confirmation_response"]),
            policy_confirmation_receipt=None
            if receipt is None
            else cast(dict[str, object], receipt),
        )
    if kind == "CONTEXT_ADJUSTMENT":
        return ContextAdjustmentControlV1(
            kind="CONTEXT_ADJUSTMENT", adjustment=cast(dict[str, object], item["adjustment"])
        )
    return RetrievalCacheRestartControlV1(
        kind="RETRIEVAL_CACHE_RESTART",
        lost_checkpoint_id=str(item["lost_checkpoint_id"]),
        lost_handle_fingerprint=str(item["lost_handle_fingerprint"]),
    )


def _binding(value: dict[str, object]) -> WorkflowExecutionBindingV1:
    return WorkflowExecutionBindingV1(
        schema_version=1,
        execution_kind=_execution_kind(value["execution_kind"]),
        run_id=str(value["run_id"]),
        langgraph_thread_id=str(value["langgraph_thread_id"]),
        graph_profile=cast(GraphProfileIdV1, value["graph_profile"]),
        graph_version=str(value["graph_version"]),
        requested_mode=cast(RequestedModeV1, value["requested_mode"]),
        checkpoint_id=None if value.get("checkpoint_id") is None else str(value["checkpoint_id"]),
        checkpoint_generation=int(str(value["checkpoint_generation"])),
        resume_target=deserialize_resume_target(value.get("resume_target")),
    )


def _admission(value: object | None) -> WorkflowExecutionAdmissionV1 | None:
    if value is None:
        return None
    item = cast(dict[str, object], value)
    return WorkflowExecutionAdmissionV1(
        schema_version=1,
        admission_id=str(item["admission_id"]),
        handoff_id=str(item["handoff_id"]),
        handoff_run_sequence=int(str(item["handoff_run_sequence"])),
        submission_kind=_submission_kind(item["submission_kind"]),
        effective_binding=_binding(cast(dict[str, object], item["effective_binding"])),
        expected_run_version=int(str(item["expected_run_version"])),
    )


def _to_handoff(row: sqlite3.Row) -> WorkflowHandoffV1:
    resume_target = deserialize_resume_target(_load_json(row["resume_target_json"]))
    execution = RunExecutionRefV1(
        schema_version=1,
        execution_kind=_execution_kind(row["execution_kind"]),
        run_id=str(row["run_id"]),
        langgraph_thread_id=str(row["langgraph_thread_id"]),
        graph_profile=cast(GraphProfileIdV1, row["graph_profile"]),
        graph_version=str(row["graph_version"]),
        requested_mode=cast(RequestedModeV1, row["requested_mode"]),
        resume_target=resume_target,
    )
    return WorkflowHandoffV1(
        schema_version=1,
        handoff_id=str(row["handoff_id"]),
        trigger_command_id=str(row["trigger_command_id"]),
        execution=execution,
        checkpoint_id=None if row["checkpoint_id"] is None else str(row["checkpoint_id"]),
        checkpoint_generation=int(row["checkpoint_generation"]),
        run_sequence=int(row["run_sequence"]),
        control_kind=_control_kind(row["control_kind"]),
        control=_control(str(row["control_kind"]), _load_json(row["control_payload_json"])),
        control_payload_hash=None
        if row["control_payload_hash"] is None
        else str(row["control_payload_hash"]),
        status=cast(WorkflowHandoffStatusV1, row["status"]),
        last_submit_reason=None
        if row["last_submit_reason"] is None
        else cast(WorkflowSubmitReasonV1, row["last_submit_reason"]),
        execution_admission=_admission(_load_json(row["execution_admission_json"])),
        applied_checkpoint_id=None
        if row["applied_checkpoint_id"] is None
        else str(row["applied_checkpoint_id"]),
        applied_checkpoint_generation=None
        if row["applied_checkpoint_generation"] is None
        else int(row["applied_checkpoint_generation"]),
        version=int(row["version"]),
    )


def _execution_kind(value: object) -> Literal["START", "RESUME"]:
    if value not in {"START", "RESUME"}:
        raise ValueError("invalid workflow execution kind")
    return cast(Literal["START", "RESUME"], value)


def _submission_kind(
    value: object,
) -> Literal["NORMAL_HANDOFF", "CONSUMED_CONTINUATION_RECOVERY"]:
    if value not in {"NORMAL_HANDOFF", "CONSUMED_CONTINUATION_RECOVERY"}:
        raise ValueError("invalid workflow submission kind")
    return cast(Literal["NORMAL_HANDOFF", "CONSUMED_CONTINUATION_RECOVERY"], value)


def _control_kind(
    value: object,
) -> Literal["NONE", "CONFIRMATION_RESPONSE", "CONTEXT_ADJUSTMENT", "RETRIEVAL_CACHE_RESTART"]:
    if value not in {
        "NONE",
        "CONFIRMATION_RESPONSE",
        "CONTEXT_ADJUSTMENT",
        "RETRIEVAL_CACHE_RESTART",
    }:
        raise ValueError("invalid workflow control kind")
    return cast(
        Literal["NONE", "CONFIRMATION_RESPONSE", "CONTEXT_ADJUSTMENT", "RETRIEVAL_CACHE_RESTART"],
        value,
    )


def _load_json(value: object | None) -> object | None:
    return None if value is None else loads(str(value))


def _stage_identity(handoff: WorkflowHandoffV1) -> WorkflowHandoffStageV1:
    return WorkflowHandoffStageV1(
        schema_version=1,
        handoff_id=handoff.handoff_id,
        trigger_command_id=handoff.trigger_command_id,
        execution=handoff.execution,
        checkpoint_id=handoff.checkpoint_id,
        checkpoint_generation=handoff.checkpoint_generation,
        control_kind=handoff.control_kind,
        control=handoff.control,
        control_payload_hash=handoff.control_payload_hash,
    )


def _require_limit(limit: int) -> None:
    if limit < 1:
        raise ValueError("limit must be positive")
