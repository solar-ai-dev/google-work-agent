"""Run-owner-local durable cancel-intent authority.

A successful RequestRunCancellation command receipt is the only durable fact
that activates cancel intent. Audit rows are deliberately excluded: they are
observability records and may be absent, retained, or purged without changing
write semantics.
"""

from __future__ import annotations

from typing import Protocol

from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.results import ResultCode

REQUEST_CANCEL_COMMAND_TYPE = "RequestRunCancellation"
RUN_AGGREGATE_TYPE = "Run"


class _DurableCancelIntentReader(Protocol):
    def has_durable_cancel_intent(self, run_id: str) -> bool: ...


def is_applied_request_cancel_receipt(
    *,
    command_type: str,
    aggregate_type: str,
    aggregate_id: str | None,
    status: str,
    result_code: str | None,
    run_id: str,
) -> bool:
    """Pure predicate for the canonical durable cancel-intent fact."""
    return (
        command_type == REQUEST_CANCEL_COMMAND_TYPE
        and aggregate_type == RUN_AGGREGATE_TYPE
        and aggregate_id == run_id
        and status == CommandReceiptStatus.APPLIED.value
        and result_code == ResultCode.TRANSITION_APPLIED.value
    )


def has_durable_cancel_intent(repository: _DurableCancelIntentReader, run_id: str) -> bool:
    """Read durable cancel intent from its command-receipt authority."""
    return repository.has_durable_cancel_intent(run_id)
