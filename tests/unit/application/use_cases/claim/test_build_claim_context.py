from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from google_work_agent.application.use_cases.claim.build_claim_context import (
    BuildClaimContextHandler,
    BuildClaimContextQueryV1,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1


class _Repository:
    def __init__(self, value: object) -> None:
        self._value = value

    def get(self, _identity: str) -> object:
        return self._value


class _UnitOfWork:
    def __init__(self) -> None:
        self.actions = _Repository(
            SimpleNamespace(
                id="action-1",
                status=ActionStatusV1.EXECUTING.value,
                tool_name="tasks_create_task",
                arguments_hash="a" * 64,
            )
        )
        self.approvals = _Repository(
            SimpleNamespace(
                id="approval-1",
                action_id="action-1",
                status=ApprovalStatusV1.CONSUMED,
                canonical_arguments_hash="a" * 64,
            )
        )
        self.execution_attempts = _Repository(
            SimpleNamespace(
                id="attempt-1",
                approval_id="approval-1",
                status=ExecutionAttemptStatusV1.CLAIMED,
            )
        )

    def __enter__(self) -> _UnitOfWork:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_application_build_is__the_single_final__claim_signing_authority() -> None:
    signed_payloads: list[dict[str, object]] = []

    def sign(payload: dict[str, object]) -> str:
        signed_payloads.append(dict(payload))
        return "application-signature"

    handler = BuildClaimContextHandler(
        unit_of_work_factory=cast(Any, _UnitOfWork),
        now_ms=lambda: 10,
        id_factory=lambda: "nonce-1",
        sign_claim_context=sign,
    )

    context = handler(
        BuildClaimContextQueryV1(
            1,
            "action-1",
            "approval-1",
            "attempt-1",
            "tasks_create_task",
            "a" * 64,
            {"task_list_id": "list-1", "payload": {"title": "Task"}},
            "service-1",
            "process-1",
        )
    )

    assert len(signed_payloads) == 1
    assert signed_payloads[0]["mcp_process_instance_id"] == "process-1"
    assert signed_payloads[0]["execution_attempt_id"] == "attempt-1"
    assert "signature" not in signed_payloads[0]
    assert context.signature == "application-signature"
