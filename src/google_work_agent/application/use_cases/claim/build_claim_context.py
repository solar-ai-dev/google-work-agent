"""Build and sign ClaimContextV2 after a durable claim commit."""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Literal

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.canonical import (
    calculate_canonical_json_hash,
)
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.ports.connector.claim_context_contract import (
    CLAIM_CONTEXT_DEFAULT_TTL_MS,
    validate_claim_ttl_ms,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class ClaimContextV2:
    claim_version: Literal[2]
    service_instance_id: str
    mcp_process_instance_id: str
    action_id: str
    approval_id: str
    execution_attempt_id: str
    tool_name: str
    approval_arguments_hash: str
    execution_arguments_hash: str
    issued_at_ms: int
    expires_at_ms: int
    nonce: str
    signature: str


@dataclass(frozen=True, slots=True)
class BuildClaimContextQueryV1:
    schema_version: Literal[1]
    action_id: str
    approval_id: str
    execution_attempt_id: str
    tool_name: str
    approval_arguments_hash: str
    final_tool_arguments: dict[str, object]
    service_instance_id: str
    mcp_process_instance_id: str


class BuildClaimContextHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        id_factory: Callable[[], str],
        sign_claim_context: Callable[[dict[str, object]], str],
        ttl_ms: int = CLAIM_CONTEXT_DEFAULT_TTL_MS,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._id_factory = id_factory
        self._sign_claim_context = sign_claim_context
        self._ttl_ms = validate_claim_ttl_ms(ttl_ms)

    def __call__(self, query: BuildClaimContextQueryV1) -> ClaimContextV2:
        with self._unit_of_work_factory() as unit_of_work:
            action = unit_of_work.actions.get(query.action_id)
            approval = unit_of_work.approvals.get(query.approval_id)
            attempt = unit_of_work.execution_attempts.get(query.execution_attempt_id)
        if action is None or approval is None or attempt is None:
            raise LookupError("committed claim binding is missing")
        if (
            approval.id != query.approval_id
            or approval.action_id != action.id
            or attempt.approval_id != approval.id
            or attempt.status is not ExecutionAttemptStatusV1.CLAIMED
            or approval.status is not ApprovalStatusV1.CONSUMED
            or action.status != ActionStatusV1.EXECUTING.value
            or action.tool_name != query.tool_name
            or action.arguments_hash != query.approval_arguments_hash
            or approval.canonical_arguments_hash != query.approval_arguments_hash
        ):
            raise PermissionError("committed claim binding is no longer current")
        execution_hash = calculate_canonical_json_hash(query.final_tool_arguments)
        issued_at_ms = self._now_ms()
        nonce = self._id_factory()
        unsigned = {
            "claim_version": 2,
            "service_instance_id": query.service_instance_id,
            "mcp_process_instance_id": query.mcp_process_instance_id,
            "action_id": action.id,
            "approval_id": approval.id,
            "execution_attempt_id": attempt.id,
            "tool_name": action.tool_name,
            "approval_arguments_hash": action.arguments_hash,
            "execution_arguments_hash": execution_hash,
            "issued_at_ms": issued_at_ms,
            "expires_at_ms": issued_at_ms + self._ttl_ms,
            "nonce": nonce,
        }
        signature = self._sign_claim_context(unsigned)
        return ClaimContextV2(
            claim_version=2,
            service_instance_id=query.service_instance_id,
            mcp_process_instance_id=query.mcp_process_instance_id,
            action_id=action.id,
            approval_id=approval.id,
            execution_attempt_id=attempt.id,
            tool_name=action.tool_name,
            approval_arguments_hash=action.arguments_hash,
            execution_arguments_hash=execution_hash,
            issued_at_ms=issued_at_ms,
            expires_at_ms=issued_at_ms + self._ttl_ms,
            nonce=nonce,
            signature=signature,
        )


def claim_context_payload(context: ClaimContextV2) -> dict[str, object]:
    return asdict(context)


__all__ = [
    "BuildClaimContextHandler",
    "BuildClaimContextQueryV1",
    "ClaimContextV2",
    "claim_context_payload",
]
