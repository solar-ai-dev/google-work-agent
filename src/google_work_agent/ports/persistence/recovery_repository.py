"""Persistence boundary for the durable RecoveryContextV1 authority."""

from __future__ import annotations

from typing import Literal, NotRequired, Protocol, Required, TypedDict

from google_work_agent.ports.system.contracts.workflow_handoff import RegisteredResumeTargetRefV2

RecoveryReasonV1 = Literal[
    "UNKNOWN_RESULT", "VERIFICATION_MISMATCH", "CHECKPOINT_MISMATCH", "CONTRACT_VIOLATION"
]


class RecoveryContextV1(TypedDict):
    """Durable RequireRecovery fact (04-A State Transition Contract SS RecoveryContextV1
    closed contract). One canonical current context per Run -- ``action_id``/
    ``execution_attempt_id``/``verification_id`` only apply when ``scope=="ACTION"``;
    RUN-scoped reasons (``CHECKPOINT_MISMATCH``, ``CONTRACT_VIOLATION``) never set them.
    Exact DB column/record shape is an adapter implementation choice; this is the
    closed logical field set only -- no additional semantic fields.
    """

    schema_version: Required[Literal[1]]
    run_id: str
    reason: RecoveryReasonV1
    scope: Literal["RUN", "ACTION"]
    pre_recovery_status: str
    recovery_fingerprint: str
    action_id: NotRequired[str]
    execution_attempt_id: NotRequired[str]
    verification_id: NotRequired[str]
    registered_resume_target: NotRequired[RegisteredResumeTargetRefV2]
    observed_external_state_fingerprint: NotRequired[str]
    verification_input_fingerprint: NotRequired[str]
    contract_or_checkpoint_fingerprint: NotRequired[str]
    last_recheck_input_hash: NotRequired[str]
    version: int
    created_at_ms: int
    updated_at_ms: int


class RecoveryConflictError(ValueError):
    """Raised when a RecoveryContext write loses its version/expectation race."""


class RecoveryRepository(Protocol):
    def store_context(self, context: RecoveryContextV1) -> RecoveryContextV1: ...
    def load_current_context(self, run_id: str) -> RecoveryContextV1 | None: ...
    def clear_context(self, run_id: str, expected_version: int) -> None: ...
    def list_candidates_bounded(self, limit: int) -> list[RecoveryContextV1]: ...
